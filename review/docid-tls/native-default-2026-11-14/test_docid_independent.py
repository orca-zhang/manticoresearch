#!/usr/bin/env python3
"""Isolate native DocID cache enablement on the latest adaptive-cache server."""
from contextlib import ExitStack
import csv
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import urllib.parse

import run_final as bench

ROOT=Path(__file__).resolve().parent
BINARY=Path('/private/tmp/manticore-admission-review-20261114/build/src/searchd')
OUT=ROOT/'docid-independent-20261114'


def pools(rows, kind):
    if kind=='point':
        result=[]
        for worker in range(8):
            rng=bench.random.Random(20261114+worker)
            result.append([bench.encoded([rng.randrange(1,rows+1)]) for _ in range(64)])
    else:result=bench.queries(rows)
    if kind=='stored':return result
    for pool in result:
        for i,(request,expected) in enumerate(pool):
            if kind in ('id-only','point'):
                sql=urllib.parse.parse_qs(request.decode())['query'][0].replace('SELECT id,body','SELECT id')
                expected=[{'id':row['id']} for row in expected]
            else:
                sql='SELECT count(*) AS n FROM docs';expected=[{'n':rows}]
            pool[i]=urllib.parse.urlencode({'query':sql}).encode(),expected
    return result


def main():
    os.environ.update(json.loads((ROOT/'calibration.json').read_text()))
    version=subprocess.check_output([str(BINARY),'--version'],text=True)
    assert 'd89cebc' in version
    OUT.mkdir(exist_ok=False)
    result=dict(source_commit='d89cebcdbee5eeaa205b6a861067b0d1219e6ea3',
        binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),version=version,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        docstore_cache=True,docstore_adaptive=True,docstore_budget_bytes=16*2**20,
        sql_query_cache_bytes=0,reader_tls=False,clients=8,rounds=6,seconds_per_arm=5,
        idle_gate=dict(seconds=30,mean_idle_percent=90,minimum_idle_percent=80,timeout_seconds=300),
        quality_rule='Retain every sample. Mean external CPU >10% machine or peak >20% schedules a complete case confirmation, never a selective round.',
        plan=[dict(rows=1000000,native_budget_bytes=16*2**20,workloads=['point','id-only','stored','full-count']),
              dict(rows=5000000,native_budget_bytes=128*2**20,workloads=['id-only','stored'])],cases=[])
    (OUT/'plan.json').write_text(json.dumps(result,indent=2)+'\n')
    ctx=mp.get_context('spawn')
    for group in result['plan']:
        rows=group['rows']
        with tempfile.TemporaryDirectory(dir=ROOT,prefix='docid-probe-') as temp,ExitStack() as stack:
            servers={}
            for label,budget in [('off',0),('on',group['native_budget_bytes'])]:
                folder=Path(temp)/label;folder.mkdir();bench.clone(ROOT/'fixtures'/f'fixture-{rows}',folder)
                server=bench.ReaderServer(str(BINARY),folder,16*2**20,docid_cache=budget)
                server.config.write_text(server.config.read_text().replace('buddy_path =','docstore_cache = 1\nbuddy_path ='))
                servers[label]=stack.enter_context(server.running())
            for kind in group['workloads']:
                name=f'{rows}-{kind}';queries=pools(rows,kind)
                assert len(queries)==8 and all(len(p)==64 for p in queries)
                assert all(len(q[1])==(256 if kind in ('stored','id-only') else 1) for p in queries for q in p)
                entry=dict(name=name,rows=rows,workload=kind,arms={},query_sha256=hashlib.sha256(b'\n'.join(q[0] for p in queries for q in p)).hexdigest())
                for label,db in servers.items():
                    sql=urllib.parse.parse_qs(queries[0][0][0].decode())['query'][0]
                    entry['arms'][label]=dict(config=db.config.read_text(),samples=[],meta=db.sql_all(sql+'; SHOW META')[1]['data'])
                path=OUT/(name+'-load.jsonl')
                with bench.LoadMonitor(path) as monitor:
                    print('Idle gate:',name,flush=True);entry['idle_gate']=monitor.wait_idle(30,90,80,300)
                    for repeat,order in enumerate(bench.orders(list(servers))):
                        for label in order:
                            db=servers[label];sample=bench.measure(db,queries,ctx,5)
                            sample.update(round=repeat,order=order,block_cache=bench.stats(db,'adaptive16'),
                                docid_used_bytes=int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value']))
                            assert (sample['docid_used_bytes']>0)==(label=='on')
                            assert sample['docid_used_bytes']<=group['native_budget_bytes']
                            entry['arms'][label]['samples'].append(sample)
                            with (OUT/(name+'-samples.jsonl')).open('a') as f:f.write(json.dumps(dict(arm=label,sample=sample))+'\n')
                        print('Round',repeat+1,name,flush=True)
                    bench.cover(monitor,sample['to_monotonic_seconds'])
                entry['thermal_before'],entry['thermal_after']=monitor.thermal_before,monitor.thermal_after
                for arm in entry['arms'].values():
                    bench.annotate(arm['samples'],path)
                    for key in ('qps','cpu_ms_per_query','docid_used_bytes','rss_bytes'):
                        arm[key]=statistics.median(s[key] for s in arm['samples'])
                result['cases'].append(entry)
                (OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
                print('RESULT',name,{label:dict(qps=round(a['qps'],1),cpu_ms_per_query=round(a['cpu_ms_per_query'],4),docid_mib=round(a['docid_used_bytes']/2**20,2)) for label,a in entry['arms'].items()},flush=True)
            for db in servers.values():bench.lifecycle(db,rows)
    result['completed']=True
    (OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    table=['# Native DocID cache: isolated SQL on/off comparison','',
           'Latest d89cebc binary; adaptive docstore cache stays at 16 MiB in both arms; native DocID budget is the only changed setting. Native budgets are 0 vs 16 MiB at 1M rows, and 0 vs 128 MiB at 5M rows. Eight clients, six alternating rounds, five seconds per arm. QPS and server CPU/query are per-arm medians. Point queries return one ID; batch queries return 256 rows. All timed responses are checked. Full count has no ID filter and is a control. Startup/construction time is excluded.','',
           '| Rows | Query | QPS off → on | QPS ratio | CPU ms/query off → on | CPU change | Native allocation MiB |',
           '| ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for c in result['cases']:
        a,b=c['arms']['off'],c['arms']['on']
        table.append(f"| {c['rows']:,} | {c['workload']} | {a['qps']:,.1f} → {b['qps']:,.1f} | {b['qps']/a['qps']:.3f}× | {a['cpu_ms_per_query']:.4f} → {b['cpu_ms_per_query']:.4f} | {(b['cpu_ms_per_query']/a['cpu_ms_per_query']-1)*100:+.2f}% | {b['docid_used_bytes']/2**20:.2f} |")
    flags=sum(s['quality_flag'] for c in result['cases'] for a in c['arms'].values() for s in a['samples'])
    table+=['',f'Quality-rule flags: {flags}. Raw sample journals, plans, configurations, query hashes, SQL plans and telemetry are preserved. Query planning can change when a complete DocID cache is admitted; this measures the whole native-cache feature, not the lookup kernel alone.','',
            'The cache holds immutable whole-chunk ID/row mappings. Its budget is additional to the docstore cache; it has no hot-entry LRU or lookup-driven shrinking. Chunk unload/remap/destruction releases allocations. These are warm synthetic ID-filter workloads, not a universal gain for full-text, dense predicates or cold startup.']
    (OUT/'REPORT.md').write_text('\n'.join(table)+'\n')
    flat=[]
    for c in result['cases']:
        for label,a in c['arms'].items():
            for s in a['samples']:
                flat.append(dict(case=c['name'],arm=label,round=s['round']+1,qps=s['qps'],
                    cpu_ms_per_query=s['cpu_ms_per_query'],p95_ms=s['p95_ms'],rss_bytes=s['rss_bytes'],
                    docid_used_bytes=s['docid_used_bytes'],completed=s['completed'],quality_flag=s['quality_flag']))
    with (OUT/'samples.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    print('Completed; quality flags:',flags,flush=True)


if __name__=='__main__':main()
