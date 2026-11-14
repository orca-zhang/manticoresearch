#!/usr/bin/env python3
"""Native DocID cache: default demand admission versus explicit disable."""
from contextlib import ExitStack
import csv
import hashlib
import http.client
import json
import multiprocessing as mp
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import urllib.parse

import run_final as bench
from test_docid_independent import pools

ROOT = Path(__file__).resolve().parent
BINARY = Path('/private/tmp/manticore-admission-review-20261114/build/src/searchd')
OUT = ROOT / 'docid-default-20261114'
COMMIT = 'af2fd38ec'
CASES = [(20000, 'stored'), (1000000, 'point'), (1000000, 'id-only'),
         (1000000, 'stored'), (1000000, 'full-count'),
         (5000000, 'id-only'), (5000000, 'stored'),
         (20000000, 'id-only'), (20000000, 'stored')]


def used(db):
    return int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value'])


def cold(db, queries):
    """512 serial requests suffice to finish a 5M-row incremental build."""
    assert used(db) == 0
    connection = http.client.HTTPConnection('127.0.0.1', db.port, timeout=30)
    before = bench.resources(db.pid)
    latencies = []
    for query in (q for pool in queries for q in pool):
        began = time.perf_counter_ns()
        bench.benchmark.execute(connection, query)
        latencies.append((time.perf_counter_ns() - began) / 1e6)
    connection.close()
    after = bench.resources(db.pid)
    return dict(latencies_ms=latencies, total_ms=sum(latencies),
                cpu_ms=(after['cpu_ns'] - before['cpu_ns']) / 1e6,
                p50_ms=statistics.median(latencies),
                p95_ms=bench.benchmark.quantile(latencies, .95),
                max_ms=max(latencies), allocated_bytes=used(db))


def main():
    os.environ.update(json.loads((ROOT / 'calibration.json').read_text()))
    version = subprocess.check_output([str(BINARY), '--version'], text=True)
    assert COMMIT in version, version
    OUT.mkdir(exist_ok=False)
    result = dict(source_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd='/private/tmp/manticore-admission-source-20261114', text=True).strip(),
        binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(), version=version,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        docstore_cache=True, docstore_budget_bytes=16 * 2**20, sql_query_cache_bytes=0,
        reader_tls=False, native_default_budget_bytes=64 * 2**20,
        clients=8, rounds=6, seconds_per_arm=5, serial_cold_queries=512,
        idle_gate=dict(seconds=30, mean_idle_percent=90, minimum_idle_percent=80, timeout_seconds=300),
        quality_rule='Retain every sample. Mean external CPU >10% machine or peak >20% flags the complete case for confirmation.',
        plan=[dict(rows=n, workload=k) for n, k in CASES], cases=[])
    (OUT / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
    ctx = mp.get_context('spawn')
    for rows, kind in CASES:
        name = f'{rows}-{kind}'
        queries = pools(rows, kind)
        expected_allocation = rows <= 5000000 and kind not in ('point', 'full-count')
        entry = dict(name=name, rows=rows, workload=kind, arms={},
                     query_sha256=hashlib.sha256(b'\n'.join(q[0] for p in queries for q in p)).hexdigest())
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='docid-default-') as temp, ExitStack() as stack:
            servers = {}
            for label, budget in [('off', 0), ('default', None)]:
                folder = Path(temp) / label
                folder.mkdir()
                bench.clone(ROOT / 'fixtures' / f'fixture-{rows}', folder)
                server = bench.ReaderServer(str(BINARY), folder, 16 * 2**20, docid_cache=budget)
                server.config.write_text(server.config.read_text().replace('buddy_path =', 'docstore_cache = 1\nbuddy_path ='))
                servers[label] = stack.enter_context(server.running())
                assert used(servers[label]) == 0
                entry['arms'][label] = dict(config=server.config.read_text(), samples=[])
            path = OUT / (name + '-load.jsonl')
            with bench.LoadMonitor(path) as monitor:
                print('Idle gate:', name, flush=True)
                entry['idle_gate'] = monitor.wait_idle(30, 90, 80, 300)
                for label, db in servers.items():
                    entry['arms'][label]['cold'] = cold(db, queries)
                    assert (used(db) > 0) == (label == 'default' and expected_allocation), (name, label, used(db))
                    assert used(db) <= 64 * 2**20
                    sql = urllib.parse.parse_qs(queries[0][0][0].decode())['query'][0]
                    entry['arms'][label]['meta'] = db.sql_all(sql + '; SHOW META')[1]['data']
                for repeat, order in enumerate(bench.orders(list(servers))):
                    for label in order:
                        db = servers[label]
                        sample = bench.measure(db, queries, ctx, 5)
                        sample.update(round=repeat, order=order,
                                      block_cache=bench.stats(db, 'adaptive16'), docid_used_bytes=used(db))
                        assert (sample['docid_used_bytes'] > 0) == (label == 'default' and expected_allocation)
                        entry['arms'][label]['samples'].append(sample)
                        with (OUT / (name + '-samples.jsonl')).open('a') as f:
                            f.write(json.dumps(dict(arm=label, sample=sample)) + '\n')
                    print('Round', repeat + 1, name, flush=True)
                bench.cover(monitor, sample['to_monotonic_seconds'])
            entry['thermal_before'], entry['thermal_after'] = monitor.thermal_before, monitor.thermal_after
            for arm in entry['arms'].values():
                bench.annotate(arm['samples'], path)
                for key in ('qps', 'cpu_ms_per_query', 'docid_used_bytes', 'rss_bytes'):
                    arm[key] = statistics.median(s[key] for s in arm['samples'])
            result['cases'].append(entry)
            (OUT / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
            print('RESULT', name, {label: dict(qps=round(a['qps'], 1),
                  cpu_ms_per_query=round(a['cpu_ms_per_query'], 4),
                  native_mib=round(a['docid_used_bytes'] / 2**20, 2))
                  for label, a in entry['arms'].items()}, flush=True)
            for db in servers.values():
                bench.lifecycle(db, rows)
    result['completed'] = True
    (OUT / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    records = [dict(case=c['name'], arm=label, round=s['round'] + 1,
                    **{k: s[k] for k in ('qps', 'cpu_ms_per_query', 'p95_ms', 'rss_bytes',
                                         'docid_used_bytes', 'completed', 'quality_flag')})
               for c in result['cases'] for label, arm in c['arms'].items() for s in arm['samples']]
    with (OUT / 'samples.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    flags = sum(s['quality_flag'] for s in records)
    print('Completed; quality flags:', flags, flush=True)


if __name__ == '__main__':
    main()
