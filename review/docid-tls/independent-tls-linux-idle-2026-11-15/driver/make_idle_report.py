#!/usr/bin/env python3
"""Validate the complete strict-idle retest and retain every timed sample."""
import argparse,csv,hashlib,json,statistics
from pathlib import Path
from idle_report_common import validate,plot

def pct(x):return f'{x:+.2f}%'
def workload(c):
 if c.get('aa'):return 'A/A, 256 rows'
 if c.get('count'):return 'Count only, 256 IDs'
 if c.get('mixed'):return f"{c['clients']//2} bulk + {c['clients']//2} hot point"
 return f"{c['batch']} stored row{'s' if c['batch']!=1 else ''}"
def table(rows):
 lines=['| Rows | Clients / workload | Block cache | Upstream QPS | TLS QPS | QPS ratio / change | CPU ms/query: upstream → TLS | CPU ratio / change |',
 '| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |']
 for r in rows:
  c=r['case'];a,b=(r['arms'][k] for k in ['baseline','tls']);q=b['qps_median']/a['qps_median'];cpu=b['server_cpu_ms_per_query_median']/a['server_cpu_ms_per_query_median']
  lines.append(f"| {c['rows']:,} | {c['clients']}: {workload(c)} | {str(c['cache_mib'])+' MiB' if c['cache_mib'] else 'Disabled'} | {a['qps_median']:,.1f} | {b['qps_median']:,.1f} | {q:.3f}× ({pct(r['qps_change_percent'])}) | {a['server_cpu_ms_per_query_median']:.4f} → {b['server_cpu_ms_per_query_median']:.4f} | {cpu:.3f}× ({pct(r['cpu_change_percent'])}) |")
 return '\n'.join(lines)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('output',type=Path);args=p.parse_args();root=args.root
 data=json.loads((root/'merged/results.json').read_text());reference=json.loads((root/'reference-results.json').read_text());protocol=json.loads((root/'protocol.json').read_text())
 total,flags=validate(data,root/'merged');assert len(data['cases'])==23
 restored=(root/'service-after-20261115.log').read_text()
 assert restored.count('ActiveState=active')==2 and all(unit in restored for unit in ['zimaos-search.service','zimaos-photos.service'])
 assert (root/'service-restore-exit-code.txt').read_text().strip()=='0'
 assert data['binary_sha256']==reference['binary_sha256']==protocol['binary_sha256']
 for name,sha in protocol['driver_sha256'].items():assert hashlib.sha256((root/'driver'/name).read_bytes()).hexdigest()==sha,name
 assert all(v['driver_sha256']==protocol['driver_sha256']['run_tls.py'] for v in data['source_phases'].values())
 old={r['case']['name']:r for r in reference['cases']}
 for r in data['cases']:
  assert r['case']==old[r['case']['name']]['case'] and r['query_sha256']==old[r['case']['name']]['query_sha256']
  g=r['idle_gate'];assert g['idle_percent_mean']>=85 and g['idle_percent_min']>=70 and g['interval_seconds']>=30
 primary=[r for r in data['cases'] if r['case']['name'].startswith('random256')]
 churn=[r for r in data['cases'] if r['case']['clients'] in [1,32]]
 other=[r for r in data['cases'] if r not in primary and r not in churn]
 datasets=[('main',data,root/'merged')]
 for folder in sorted(root.glob('repeat-*'),key=lambda p:(p.name!='repeat-low',p.name)):
  if folder.is_dir() and (folder/'results.json').exists():
   d=json.loads((folder/'results.json').read_text());validate(d,folder);assert d['binary_sha256']==data['binary_sha256'];datasets.append((folder.name,d,folder))
   for r in d['cases']:assert r['query_sha256']==old[r['case']['name']]['query_sha256']
 expected_repeats={r['case']['name'] for r in data['cases'] if any(s['quality_flag'] for a in r['arms'].values() for s in a['samples'])}
 observed_repeats=[r['case']['name'] for _,d,_ in datasets[1:] for r in d['cases']]
 assert expected_repeats==set(observed_repeats) and len(observed_repeats)==len(expected_repeats)
 diagnostics=json.loads((root/'diagnostic-status.json').read_text());diagrows=[];diagsamples=[]
 assert {s['phase'] for s in diagnostics}=={'original32-16m','aa32-16m','original32-0m','aa32-0m'} and len(diagnostics)==4
 for status in diagnostics:
  folder=root/status['phase'];d=json.loads((folder/'results.json').read_text()) if (folder/'results.json').exists() else None
  complete=bool(d and d.get('completed'))
  assert complete==(status['returncode']==0)
  if complete:
   validate(d,folder)
   expected=data['binary_sha256']['baseline']
   assert d['binary_sha256']==({'baseline':expected,'tls':expected} if status['same_upstream_binary_both_arms'] else data['binary_sha256'])
  annotated={(r['case']['name'],arm,s['round']):s for r in d['cases'] for arm,a in r['arms'].items() for s in a['samples']} if complete else {}
  for journal in sorted(folder.glob('*-samples.jsonl')):
   records=[json.loads(line) for line in journal.read_text().splitlines()];name=journal.name.removesuffix('-samples.jsonl')
   diagsamples.extend((status['phase'],name,x['arm'],annotated.get((name,x['arm'],x['sample']['round']),x['sample'])) for x in records)
  diagrows.append((status,d,complete))
 args.output.mkdir(exist_ok=True,parents=True);plot(primary,args.output)
 gates=[r['idle_gate'] for r in data['cases']]
 on=[r['cpu_change_percent'] for r in primary if r['case']['cache_mib']==16];off=[r['cpu_change_percent'] for r in primary if not r['case']['cache_mib']]
 report=f'''# PR #5045: independent Linux reader TLS retest with a strict idle gate

This fresh experiment tests **reader TLS (thread-local storage) only**, independently of #5042. It uses the same upstream/TLS binaries, deterministic fixtures and query pools as the [earlier Linux run](https://github.com/orca-zhang/manticoresearch/blob/b3b5122cbaa1bbb33fe0eb68e4df3d5a7a87af09/review/docid-tls/independent-tls-linux-2026-11-14/REPORT.md). Measured on November 15, 2026 (Asia/Shanghai), after temporarily stopping `zimaos-search.service` and `zimaos-photos.service` with user authorization. Both services are restored after the benchmark by a host-side exit handler. The full matrix uses a stricter idle gate and external-load thresholds. Earlier measurements remain available; no earlier rounds are substituted into this retest.

At eight clients and 256 stored rows/query, observed server CPU/query changes are **{pct(min(on))} to {pct(max(on))} with the default 16 MiB block cache**, and **{pct(min(off))} to {pct(max(off))} with the block cache disabled**. The tables include negative observations, same-binary controls and per-pair dispersion. These are measurements on one four-core host, not a universal speedup or no-regression guarantee.

## Scope, source and method

- Intel N100, 4 cores / 4 hardware threads, nominal 16 GB RAM, x86-64 Linux 6.18.9 / ZimaOS 1.8.1-alpha2; isolated Ubuntu 24.04 container, SSD storage. Clang 18.1.3, `-O2 -DNDEBUG`, no `-march=native`. No governor, CPU affinity or quota changes. Other host services remain enabled; the external-load audit describes the observed environment.
- Upstream base `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`; TLS arm adds only the production patch from #5045 head `019868e9f79d1bb2bd1f96dafb88ef20acd45418`. Both retain the original upstream single-lock CRC32 block cache. No adaptive cache, sharding, XXH3 block-cache change or native DocID cache is included.
- Binary SHA-256: upstream `{data['binary_sha256']['baseline']}`; TLS `{data['binary_sha256']['tls']}`. Both were validated by the earlier 497-test native suites and five reader tests ×20 per arm; binaries were reused without rebuilding. Exactly one of 332 build objects differed (`docstore.cpp.o`); original build/test manifests are linked above.
- 20k / 1M / 10M rows; 128-byte stored-only text; 16 KiB/LZ4 blocks; flushed rowwise disk chunks; warm OS file pages. Fixture files are rehashed against the original manifest before this run. Every response validates exact IDs/text. Each complete case also validates ordered REPLACE/FLUSH/DROP/recreate behavior in both arms.
- Eight server workers throughout; 1/8/32 loopback clients share the host CPU budget with the server. SQL result cache off; original upstream 8 MiB reader-buffer budget. Stored-field queries create query-scoped docstore sessions even with HTTP keep-alive.
- Six balanced alternating AB/BA rounds ×5 seconds/arm. Full query-pool warmup before each interval; only one arm receives timed traffic at a time. Main matrix: **23 comparisons / 276 timed samples / {total:,} validated timed queries**.
- Before every case: 30 seconds with mean idle ≥85%, minimum idle ≥70%. All 23 primary gates passed; observed gate means span {min(g['idle_percent_mean'] for g in gates):.1f}%–{max(g['idle_percent_mean'] for g in gates):.1f}%, with the lowest one-second idle observation {min(g['idle_percent_min'] for g in gates):.1f}%. A one-second host monitor estimates external CPU by subtracting observed benchmark descendants. Newly started or already-exited descendants can inflate the residual estimate; load flags are conservative diagnostics, not proof of unrelated load.
- Policy fixed before timing: flag a timed interval if external mean exceeds 15% of machine capacity or any overlapping one-second peak exceeds 30%. Flagged main intervals: **{flags}**. Repeat every affected complete primary comparison once in full; preserve all original rounds and repeats. Absolute-load thresholds do not establish perfect paired load balance; the audit below shows that balance without filtering samples.
- QPS = completed queries / wall time. CPU/query = server process user+system CPU delta / completed queries; clients and warmup excluded from the numerator. Linux `/proc/PID/stat` uses 10 ms CPU ticks (100 Hz). Tables compare per-arm medians; QPS and CPU ratios are TLS/upstream. **Higher QPS is better; lower CPU/query is better.** Small low-CPU differences have limited resolution.
- Primary 1/8-client cases use the original CPython HTTP client. Primary 32-client cases use the same client-only single-write framing in both arms as the earlier Linux comparison: identical request bytes, no request retries, no ignored errors, unchanged engine binaries. The separate original-transport diagnostics below test the earlier failure path. These counts are not one transport-identical scaling curve.

## Data scale: 256 stored rows/query

{table(primary)}

![Reader TLS effect by data scale](reader-tls-independent.png)

Whiskers show the minimum/maximum of six paired changes, not confidence intervals. Points compare per-arm medians. Three sizes do not identify a universal optimum, and cache-on/cache-off absolute performance is a different comparison from the TLS effect.

## Smaller results, mixed workload and controls

{table(other)}

A/A uses the exact same upstream binary under both labels. Count-only queries do not retrieve stored fields. Interpret small changes alongside these controls and paired dispersion.

## Short-lived sessions and concurrency

{table(churn)}

The generation counter is loaded on lookup and advanced on successful reader insertions/removals (and initialization/destruction), not once per returned row. Unrelated sessions can invalidate another worker's TLS entry. End-to-end session churn includes counter updates, invalidation, miss locking, query work and transport; it does not isolate the atomic counter's cost. Mixed aggregate CPU/query also depends on the achieved bulk/point completion ratio.

| Clients | Cache | Bulk QPS: upstream → TLS | Bulk change | Hot point QPS: upstream → TLS | Point change |
| ---: | --- | ---: | ---: | ---: | ---: |
'''
 for r in data['cases']:
  if not r['case'].get('mixed'):continue
  a,b=(r['arms'][k] for k in ['baseline','tls']);c=r['case']
  report+=f"| {c['clients']} | {str(c['cache_mib'])+' MiB' if c['cache_mib'] else 'Disabled'} | {a['bulk_qps_median']:,.1f} → {b['bulk_qps_median']:,.1f} | {pct((b['bulk_qps_median']/a['bulk_qps_median']-1)*100)} | {a['point_qps_median']:,.1f} → {b['point_qps_median']:,.1f} | {pct((b['point_qps_median']/a['point_qps_median']-1)*100)} |\n"
 report+='\n## Verification repeats\n\n'
 repeats=[r for phase,d,_ in datasets[1:] for r in d['cases']]
 repeat_flags=sum(s['quality_flag'] for _,d,_ in datasets[1:] for r in d['cases'] for a in r['arms'].values() for s in a['samples'])
 report+=(table(repeats)+f'\n\nOriginal rounds remain above; none are replaced. Full repeated comparisons: {len(repeats)}; flagged repeat intervals: {repeat_flags}. Repeat quality annotations are retained even if a flag recurs.\n') if repeats else 'No primary comparison exceeded the predeclared external-load thresholds; no load-triggered repeat was required.\n'
 point_repeat=next((r for r in repeats if r['case']['name']=='point-20000-16m'),None)
 if point_repeat:
  original=next(r for r in data['cases'] if r['case']['name']=='point-20000-16m')
  report+=f"\nThe eight-client/default-cache point case records QPS {pct(original['qps_change_percent'])} in the primary comparison and {pct(point_repeat['qps_change_percent'])} in its complete repeat (repeat CPU/query {pct(point_repeat['cpu_change_percent'])}). This is a retained negative throughput observation even though CPU/query is close to flat; a universal no-regression claim is not supported.\n"
 report+='\n## Original-transport 32-client diagnostics\n\nThe earlier Linux run encountered an unconfirmed warmup error and a later connection reset with the original HTTP client. This retest preserves that history and tests original framing separately from the matched single-write primary cases. Each diagnostic is one six-round attempt; a failure retains every completed interval and its logs, with no request retries. A successful attempt does not prove the earlier failures unrelated to TLS.\n\n| Diagnostic | Actual binaries | Completed | Recorded timed samples | QPS B/A change | CPU/query B/A change |\n| --- | --- | --- | ---: | ---: | ---: |\n'
 for status,d,complete in diagrows:
  samples=sum(1 for phase,*_ in diagsamples if phase==status['phase']);r=d['cases'][0] if complete else None
  report+=f"| {status['phase']} | {'Upstream / upstream (A/A)' if status['same_upstream_binary_both_arms'] else 'Upstream / TLS'} | {'Yes' if complete else 'No; see logs'} | {samples} | {pct(r['qps_change_percent']) if r else 'Incomplete'} | {pct(r['cpu_change_percent']) if r else 'Incomplete'} |\n"
 audit=json.loads((root/'diagnostic-failure-provenance.json').read_text())
 upstream_resets=[x for x in audit if x.get('connection_reset') and x.get('active_binary_is_unmodified_upstream')]
 if upstream_resets:
  report+='\nThe recorded journal prefix and warmup traceback place the connection reset in `original32-16m` at the unmodified upstream arm, round 5 (zero-based round 4), before that interval was recorded. This arm attribution is an inference from the fixed AB/BA plan and validated completed-prefix order; see `diagnostic-failure-provenance.json`. The symptom therefore is not exclusive to the TLS binary. Its root cause remains unconfirmed, and this observation is not a proof of arbitrary concurrent reader reclamation safety.\n'
 report+='\n## Paired load and dispersion audit\n\nEvery comparison is retained. External CPU percentages describe machine capacity. Paired changes show the six round-wise TLS/upstream ratios; they differ from ratios of per-arm medians.\n\n| Case | External CPU median: upstream → TLS | External peak, either arm | Paired QPS min…max | Paired CPU/query min…max |\n| --- | ---: | ---: | ---: | ---: |\n'
 for r in data['cases']:
  a,b=(r['arms'][k] for k in ['baseline','tls']);ea=statistics.median(s['external_cpu_mean_machine_percent'] for s in a['samples']);eb=statistics.median(s['external_cpu_mean_machine_percent'] for s in b['samples']);peak=max(s['external_cpu_peak_machine_percent'] for arm in r['arms'].values() for s in arm['samples']);q=r['paired_qps_changes_percent'];c=r['paired_cpu_changes_percent']
  report+=f"| {r['case']['name']} | {ea:.1f}% → {eb:.1f}% | {peak:.1f}% | {pct(min(q))} … {pct(max(q))} | {pct(min(c))} … {pct(max(c))} |\n"
 report+='''
## Interpretation and reader lifetime

A decoded block-cache hit skips `ReadFromFile()` and the reader lookup optimized by this patch. Cache-off batches expose lookup overhead more often; other query costs and session churn can reduce reuse. Neither larger data nor greater concurrency guarantees a larger benefit. Hardware/compiler/dependency differences prevent attributing the difference from Apple M4 solely to Linux.

The TLS entry is a borrowed reader pointer. Acquire/release generation checks invalidate entries across ordered changes; they are not memory reclamation and do not close a check/use race. The session/reader and index must outlive the read, the same mutable reader must be used serially, and shutdown must be quiescent. The upstream lookup also unlocks before using the pointer. Arbitrary concurrent destruction of the same reader is not made safe by this patch. Ordered lifecycle tests and successful benchmarks are not a sanitizer proof of concurrent reclamation.

## Reproduce and audit

`protocol.json` records the fixed idle/quality policy, binary/fixture identities and driver hashes. `prepare_idle.py` changes only the load gate, external-load thresholds and metadata from the earlier driver; it asserts the query-pool and timed measurement regions are byte-identical. `run_idle.py` runs the matrix and diagnostics. The source/build/test provenance is retained in the earlier immutable Linux evidence; this retest reuses those exact binaries. No rebuild is needed to reproduce using the retained task workspace on host 89.

For report regeneration, extract the evidence archive, install Matplotlib, then run:

```sh
python3 driver/make_idle_report.py . report
```

`summary.csv` includes every complete main/repeat/diagnostic comparison. `samples.csv` includes all recorded main/repeat/diagnostic intervals; failed intervals with no completed aggregate are represented by logs, not fabricated throughput samples. Full JSON journals, telemetry, lifecycle results and both client implementations are retained.
'''
 (args.output/'REPORT.md').write_text(report)
 with (args.output/'summary.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['phase','case','baseline_qps','tls_or_B_qps','qps_ratio','qps_change_percent','baseline_cpu_ms_per_query','tls_or_B_cpu_ms_per_query','cpu_ratio','cpu_change_percent'])
  complete_datasets=datasets+[(s['phase'],d,root/s['phase']) for s,d,complete in diagrows if complete]
  for phase,d,_ in complete_datasets:
   for r in d['cases']:
    a,b=(r['arms'][k] for k in ['baseline','tls']);w.writerow([phase,r['case']['name'],a['qps_median'],b['qps_median'],b['qps_median']/a['qps_median'],r['qps_change_percent'],a['server_cpu_ms_per_query_median'],b['server_cpu_ms_per_query_median'],b['server_cpu_ms_per_query_median']/a['server_cpu_ms_per_query_median'],r['cpu_change_percent']])
 with (args.output/'samples.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['phase','case','arm','round','qps','server_cpu_ms_per_query','completed','elapsed_seconds','client_cpu_cores','quality_flag','external_mean_machine_pct','external_peak_machine_pct'])
  records=[(phase,r['case']['name'],arm,s) for phase,d,_ in datasets for r in d['cases'] for arm,a in r['arms'].items() for s in a['samples']]+diagsamples
  for phase,case,arm,s in records:w.writerow([phase,case,arm,s['round'],s['qps'],s['server_cpu_ms_per_query'],s['completed'],s['elapsed_seconds'],s['client_cpu_cores'],s.get('quality_flag','see source JSON/logs'),s.get('external_cpu_mean_machine_percent',''),s.get('external_cpu_peak_machine_percent','')])
 print(json.dumps({'primary_cases':23,'primary_samples':276,'recorded_samples':len(records),'main_queries':total,'flags':flags,'diagnostic_samples':len(diagsamples)}))
if __name__=='__main__':main()
