#!/usr/bin/env python3
"""Validate every Linux sample and generate English tables and a scale chart."""
import argparse,csv,json,statistics
from pathlib import Path
from report_common import validate,plot

def pct(v):return f'{v:+.2f}%'
def arms(row):return [row['arms'][k] for k in ('baseline','tls')]
def workload(c):
 if c.get('aa'):return 'A/A: same upstream binary, 256 rows'
 if c.get('count'):return 'Count only, 256 IDs'
 if c.get('mixed'):return f"{c['clients']//2} bulk + {c['clients']//2} hot point clients"
 return f"Random, {c['batch']} stored row{'s' if c['batch']!=1 else ''}"
def table(rows):
 out=['| Rows | Clients / workload | Block cache | Upstream QPS | TLS QPS | TLS / upstream QPS | CPU ms/query: upstream → TLS | TLS / upstream CPU |',
 '| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for row in rows:
  c=row['case'];a,b=arms(row)
  qr=b['qps_median']/a['qps_median'];cr=b['server_cpu_ms_per_query_median']/a['server_cpu_ms_per_query_median']
  out.append(f"| {c['rows']:,} | {c['clients']}: {workload(c)} | {c['cache_mib']} MiB | {a['qps_median']:,.1f} | {b['qps_median']:,.1f} | {qr:.3f}× ({pct(row['qps_change_percent'])}) | {a['server_cpu_ms_per_query_median']:.4f} → {b['server_cpu_ms_per_query_median']:.4f} | {cr:.3f}× ({pct(row['cpu_change_percent'])}) |")
 return '\n'.join(out)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('measurement',type=Path);p.add_argument('output',type=Path);p.add_argument('--repeat',type=Path);args=p.parse_args()
 data=json.loads((args.measurement/'results.json').read_text());total,flags=validate(data,args.measurement)
 primary=[x for x in data['cases'] if x['case']['name'].startswith('random256')]
 churn=[x for x in data['cases'] if x['case']['name'].startswith(('churn','mixed-c32'))]
 other=[x for x in data['cases'] if x not in primary and x not in churn]
 samples=sum(len(a['samples']) for x in data['cases'] for a in x['arms'].values())
 repeat=json.loads((args.repeat/'results.json').read_text()) if args.repeat else None
 datasets=[('main',data)]
 if repeat:
  rt,rf=validate(repeat,args.repeat);assert repeat['binary_sha256']==data['binary_sha256'];datasets.append(('repeat',repeat))
  orig={x['case']['name']:x for x in data['cases']}
  for row in repeat['cases']:assert orig[row['case']['name']]['query_sha256']==row['query_sha256']
 partial_path=args.measurement.parent/'diagnostics.json'
 partial=json.loads(partial_path.read_text()) if partial_path.exists() else None
 args.output.mkdir(parents=True,exist_ok=True)
 plot(primary,args.output)
 on=[x['qps_change_percent'] for x in primary if x['case']['cache_mib']==16]
 off=[x['qps_change_percent'] for x in primary if x['case']['cache_mib']==0]
 report=f'''# PR #5045: independent Linux/x86-64 reader TLS benchmark

This tests **reader TLS only**, independently of PR #5042. Both arms retain the original upstream single-mutex, CRC32 docstore block cache. No adaptive cache, cache sharding, XXH3 block-cache change or native DocID lookup cache is included.

With 8 clients returning 256 stored rows/query, observed server CPU/query changes are **{pct(min(x['cpu_change_percent'] for x in primary if x['case']['cache_mib']==16))} to {pct(max(x['cpu_change_percent'] for x in primary if x['case']['cache_mib']==16))}** at the default 16 MiB cache, and **{pct(min(x['cpu_change_percent'] for x in primary if x['case']['cache_mib']==0))} to {pct(max(x['cpu_change_percent'] for x in primary if x['case']['cache_mib']==0))}** with it disabled. This Linux run does not reproduce the larger M4 cache-off CPU saving. Host services remain active and their load is uneven between some paired arms, so wall-time QPS differences require the load audit and controls below; these QPS figures do not establish an isolated TLS speedup.

## Comparable source and build

- Upstream base: `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`.
- TLS arm: the same base plus the exact `src/docstore.cpp` patch from #5045 head `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
- Same five reader tests installed before either build. Same worktree revision, generated version headers, dependencies and build directory. Exactly one of 332 object files changed: `src/CMakeFiles/lmanticore.dir/docstore.cpp.o`. The complete object manifests are retained.
- Ubuntu Clang 18.1.3, `-O2 -DNDEBUG`, no `-march=native`. MCL API-only; rowwise workloads. ICU uses the same system library in both arms. Full configuration and package versions are retained.
- Binary SHA-256: upstream `{data['binary_sha256']['baseline']}`; TLS `{data['binary_sha256']['tls']}`.

## Method

- Intel N100, 4 cores / 4 hardware threads, 16 GB nominal RAM (15 GiB Linux usable), x86-64 ZimaOS 1.8.1-alpha2 / Linux 6.18.9. Isolated Ubuntu 24.04 container on native Linux, SSD fixture storage; no CPU quota or affinity changes. Existing CPU governor retained.
- Identical deterministic fixtures to the Apple M4 comparison: 20k / 1M / 10M rows; one 128-byte stored-only text field, 16 KiB blocks, LZ4 compression, flushed disk chunks. Fixture hashes and imported table-registry path rewrites are recorded. Every response validates exact IDs/text; fixture counts and first/middle/last rows are checked in both binaries before timing.
- Loopback clients share the same four-core host and CPU budget as the server. 8 server worker threads throughout. Primary cases have 8 clients; additional point/session-churn cases have 1 and 32 clients, and mixed cases have 8 and 32. HTTP loopback keep-alive; original CPython writes for 1/8 clients, matched single-write request framing for all 32-client primary cases (see diagnostics); SQL result cache disabled; upstream default 8 MiB reader-buffer budget. A query-scoped docstore session is created/cleaned up for stored-field materialization, even with HTTP keep-alive.
- 6 balanced AB/BA rounds × 5 seconds/arm. Each worker warms its full fixed query pool before each timed interval. Only one arm receives benchmark traffic at a time. All **{samples} timed samples / {total:,} validated timed queries** are retained.
- QPS = completed queries / wall time. Server CPU/query = process user+system CPU delta from `/proc/PID/stat` / completed queries, excluding clients and warmup; Linux process CPU tick resolution is 10 ms (100 Hz); low-CPU single-client percentage differences have limited precision. Per-arm medians are shown. **QPS multiplier = TLS/upstream (higher is better); CPU multiplier = TLS/upstream (lower is better).** Percentages compare those medians, not the median of per-round percentages.
- Existing host services are retained: this is a co-resident-service comparison. Warm OS file pages; no cold-storage claim. 30-second idle gate: mean ≥60%, minimum ≥30%. Continuous 1-second host CPU telemetry subtracts benchmark descendants to estimate external CPU. Predeclared flags: external mean >45% of the machine or any overlapping interval >70%. Flags: **{flags}**. These thresholds detect high absolute external usage; they do not test load balance between paired arms. The separate load audit reports that balance for every case. All samples remain available; no rounds are selected by QPS.
- Before any timed sample, an initial idle preflight failed the stricter 85%/70% gate. Its telemetry is retained separately; the co-resident-service criteria above were fixed before starting timing. The same Linux runtime defaults are used in both arms. No macOS stack-calibration environment is imported.

## Data scale: 256 stored rows/query

{table(primary)}

![Linux TLS effect by table size](reader-tls-independent.png)

Points compare per-arm medians; whiskers show min/max of the 6 paired changes, **not confidence intervals**. Three sizes do not locate a universal optimum. The plot retains negative results. Cache-on/cache-off absolute performance is a separate comparison and must not be labeled as a TLS speedup.

## Smaller results, mixed workload and controls

{table(other)}

A/A uses the same upstream binary under both labels. Count-only queries do not retrieve stored fields. Small changes must be interpreted alongside these controls and the paired samples.

## More short-lived sessions

{table(churn)}

Aggregate CPU/query in mixed cases also depends on the achieved work mix; interpret it alongside both group throughputs. These are end-to-end session-churn measurements, including generation updates, cross-thread invalidation, locking on misses, query handling and response transport. They do not isolate the atomic counter's cost or establish a universal maximum-concurrency result. On a four-core host, client and server CPU share the same CPU budget; client CPU and latency are retained per sample. No TCP reconnect workload is conflated with docstore-session lifetime.

### Mixed-workload groups

| Clients | Cache | Bulk QPS: upstream → TLS | Bulk change | Hot point QPS: upstream → TLS | Point change |
| ---: | ---: | ---: | ---: | ---: | ---: |
'''
 for row in data['cases']:
  if not row['case'].get('mixed'):continue
  c=row['case'];a,b=arms(row)
  report+=f"| {c['clients']} | {c['cache_mib']} MiB | {a['bulk_qps_median']:,.1f} → {b['bulk_qps_median']:,.1f} | {pct((b['bulk_qps_median']/a['bulk_qps_median']-1)*100)} | {a['point_qps_median']:,.1f} → {b['point_qps_median']:,.1f} | {pct((b['point_qps_median']/a['point_qps_median']-1)*100)} |\n"
 if repeat:
  report+=f'''\n## Complete verification repeats

The flagged comparisons were repeated in full, with the original query and binary hashes. Original rounds are retained above; none were substituted. Additional timed queries: **{rt:,}**; repeat flags: **{rf}**.

{table(repeat['cases'])}
'''
 if partial:
  reproduced=('The 32-client A/A diagnostic reproduced a connection reset while **both labels ran the unmodified upstream binary**.' if partial['upstream_aa32_connection_reset'] else 'The 32-client A/A diagnostic is retained; it did not capture a connection reset in its completed intervals.')
  report+=f"\n## High-concurrency transport diagnostics\n\nThe initial 32-client/default-cache attempt ended in a readiness timeout during the TLS arm's final warmup, after 11 recorded timed samples. The first driver waited for a token before checking asynchronous worker errors, so the underlying worker exception was not captured. Warmup error propagation and server-log retention were added and selfchecked. A subsequent 32-client/cache-off attempt captured `ConnectionResetError`, with server logs reporting HTTP receive errors / `EAGAIN`. {reproduced} The first generic timeout's specific cause remains unconfirmed.\n\nAll four 32-client comparisons in the primary tables were then measured using a matched client-only variant: **exactly the same HTTP bytes, coalesced into one send call per request**, in both arms. The client selfcheck asserts byte equality with the original CPython HTTP client. There are no request retries or ignored errors. Engine binaries and query pools are unchanged; every response is still validated. Original 1/8-client comparisons retain their original client. Consequently, concurrency counts here describe individual paired experiments and must not be interpreted as a single transport-identical scaling curve.\n\nThe original 19 complete comparisons were retained intact. All earlier completed and incomplete high-concurrency/A/A diagnostic intervals remain in their source directories, `diagnostics.json`, and `samples.csv`: **{partial['recorded_samples']} additional recorded samples / {partial['recorded_timed_queries']:,} validated queries in recorded intervals**. Failed intervals with incomplete aggregate results are documented by traceback/logs and are not turned into throughput samples. Their quality annotations were not completed when a case failed. No round was selected by QPS. Both original and diagnostic driver versions, the client transport variant and its protocol manifest are archived. The failures remain unresolved: successful runs with the modified client do not establish that the original failures are unrelated to TLS. They also do not prove arbitrary concurrent reader reclamation safe.\n"
 report+='\n## Wall-time load audit\n\nThe host retains its existing services. This descriptive audit reports load balance and paired QPS dispersion for every case. It does not filter or replace any samples. A throughput difference accompanied by unequal external load does not establish an isolated TLS speedup. CPU/query and the same-binary controls remain essential.\n\n| Case | External CPU, machine %: upstream → TLS | Median paired QPS change | Paired QPS min…max |\n| --- | ---: | ---: | ---: |\n'
 for row in data['cases']:
  a,b=arms(row);ea=statistics.median(s['external_cpu_mean_machine_percent'] for s in a['samples']);eb=statistics.median(s['external_cpu_mean_machine_percent'] for s in b['samples']);paired=row['paired_qps_changes_percent']
  report+=f"| {row['case']['name']} | {ea:.1f} → {eb:.1f} | {pct(statistics.median(paired))} | {pct(min(paired))} … {pct(max(paired))} |\n"
 report+='''
## Interpretation and lifetime safety

A decoded block-cache hit skips `ReadFromFile()` and therefore skips the reader lookup optimized by this PR. Cache-off batched reads expose that lookup more often. Other query costs grow with the workload, and frequent reader insertion/removal advances the process-wide generation, invalidating TLS entries on other workers. Neither larger tables nor higher concurrency guarantees a larger benefit.

The one-entry TLS cache holds a **borrowed pointer**. Acquire/release generation checks invalidate it; they do not reclaim memory or close a check/use race. The existing contract must keep the same reader/session and index alive during a read, serialize use of the same mutable reader, and make shutdown quiescent. The upstream locked path also releases the registry lock before reader use. Arbitrary deletion of the same reader during an active read is not made safe by this patch.

Both arms passed all 497 native tests and five reader tests ×20; logs retain the actual test totals. Each measured comparison also runs ordered REPLACE/FLUSH/DROP/recreate checks in both arms. These checks respect the lifetime contract; they are not a new sanitizer proof of concurrent reclamation.

This is one four-core x86-64 host, one compiler and a synthetic stored-text workload. Small changes within control variation should not be described as reliable gains or regressions. Hardware, worker count, selectivity, block hit rate and the proportion of reader-lookup work can change the outcome.

## Reproduce and audit

See `BUILD.md`, the exact production/common-test patches, package and compile-command manifests, object hashes, test logs, preregistered plans, complete JSON results, per-round journals and CPU telemetry. `summary.csv` and `samples.csv` include every measured case. The separate Apple M4 report remains unchanged. Hardware, compiler and dependency versions differ between the two hosts, so this is not an isolated comparison of operating systems.

```sh
python3 driver/run_tls.py --selfcheck
python3 driver/coalesced_http.py
python3 reproduce.py --selfcheck
# Fresh benchmark workspace only; see BUILD.md for binaries and fixtures:
python3 reproduce.py
# Regenerate this saved report without running a benchmark:
python3 driver/make_linux_report.py merged report --repeat repeat
```

`run_tls.py` expects `searchd-baseline` and `searchd-tls` beside its `driver` directory. Benchmarks use only the Python standard library; plot regeneration additionally requires Matplotlib.
'''
 (args.output/'REPORT.md').write_text(report)
 with (args.output/'summary.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['phase','case','rows','clients','cache_mib','baseline_qps','tls_qps','qps_multiplier','qps_change_percent','baseline_cpu_ms_per_query','tls_cpu_ms_per_query','cpu_multiplier','cpu_change_percent'])
  for phase,dataset in datasets:
   for row in dataset['cases']:
    c=row['case'];a,b=arms(row);w.writerow([phase,c['name'],c['rows'],c['clients'],c['cache_mib'],a['qps_median'],b['qps_median'],b['qps_median']/a['qps_median'],row['qps_change_percent'],a['server_cpu_ms_per_query_median'],b['server_cpu_ms_per_query_median'],b['server_cpu_ms_per_query_median']/a['server_cpu_ms_per_query_median'],row['cpu_change_percent']])
 with (args.output/'samples.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['phase','case','arm','round','qps','server_cpu_ms_per_query','completed','elapsed_seconds','client_cpu_cores','quality_flag','external_mean_machine_pct','external_peak_machine_pct'])
  for phase,dataset in datasets:
   for row in dataset['cases']:
    for label,arm in row['arms'].items():
     for s in arm['samples']:w.writerow([phase,row['case']['name'],label,s['round'],s['qps'],s['server_cpu_ms_per_query'],s['completed'],s['elapsed_seconds'],s['client_cpu_cores'],s['quality_flag'],s['external_cpu_mean_machine_percent'],s['external_cpu_peak_machine_percent']])
  if partial:
   for case in partial['cases']:
    for row in case['samples']:
     s=row['sample'];w.writerow(['diagnostic-'+case['phase'],case['case'],row['arm'],s['round'],s['qps'],s['server_cpu_ms_per_query'],s['completed'],s['elapsed_seconds'],s['client_cpu_cores'],'see source logs','',''])
 print(json.dumps({'samples':samples,'queries':total,'flags':flags}))
if __name__=='__main__':main()
