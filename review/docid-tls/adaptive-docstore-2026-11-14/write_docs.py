#!/usr/bin/env python3
"""Write the connected English review narrative from validated final measurements."""
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(sys.argv[1]); OUT=Path(sys.argv[2])
DATA=ROOT/'raw' if (ROOT/'raw').is_dir() else ROOT
summary=json.loads((OUT/'summary.json').read_text())
main=json.loads((DATA/'measurement/results.json').read_text())
controls=json.loads((DATA/'controls/results.json').read_text())
identity=json.loads((ROOT/'publish-identity.json').read_text())
rows=sorted({s['rows'] for s in summary['primary']})
lookup={(s['rows'],s['arm']):s for s in summary['primary']}
def q(r,a):return lookup[r,a]['qps']
def cpu(r,a):return lookup[r,a]['cpu_ms_per_query']
def ratio(r,a):return q(r,a)/q(r,'off')
def delta(r,a):return (cpu(r,a)/cpu(r,'off')-1)*100
def qtable():
    text=['| Rows | Off | Default manual 16 MiB | Adaptive 16 MiB | Adaptive 128 MiB | Manual 512 MiB | Adaptive 512 MiB |',
          '| ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:
        text.append('| '+f'{r:,} | {q(r,"off"):,.1f} (1.00×) | '+' | '.join(f'{q(r,a):,.1f} ({ratio(r,a):.2f}×)' for a in ('manual16','adaptive16','adaptive128','manual512','adaptive512'))+' |')
    return '\n'.join(text)
def ctable():
    text=['| Rows | Off | Manual 16 MiB | Adaptive 16 MiB | Adaptive 128 MiB | Manual 512 MiB | Adaptive 512 MiB |',
          '| ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:text.append('| '+f'{r:,} | '+' | '.join(f'{cpu(r,a):.4f}' for a in ('off','manual16','adaptive16','adaptive128','manual512','adaptive512'))+' |')
    return '\n'.join(text)
mem=summary['memory']
def mm(arm,stage,key):return statistics.median(m[key] for m in mem if m['arm']==arm and m['stage']==stage)
mtable=['| Access phase (same 5M-row table) | Manual 512 MiB RSS | Adaptive 512 MiB RSS | Adaptive footprint | Adaptive entries / mapped |',
        '| --- | ---: | ---: | ---: | ---: |']
for stage,label in [('broad','5M broad'),('hot','20k hot'),('broad-again','5M broad again')]:
    mtable.append(f'| {label} | {mm("manual512",stage,"rss_mib"):.1f} | {mm("adaptive512",stage,"rss_mib"):.1f} | {mm("adaptive512",stage,"footprint_mib"):.1f} | {mm("adaptive512",stage,"used_mib"):.1f} / {mm("adaptive512",stage,"mapped_mib"):.1f} |')
scan=next(c for c in controls['cases'] if c['name'].startswith('scan'))
aa=next(c for c in controls['cases'] if c['name'].startswith('random'))
st=['| 20M advancing scan | QPS | QPS / off | Server CPU ms/query | CPU vs off |','| --- | ---: | ---: | ---: | ---: |']
for a in ('off','manual512','adaptive512'):
    s=scan['arms'][a];base=scan['arms']['off']
    st.append(f'| {a} | {s["qps"]:,.1f} | {s["qps"]/base["qps"]:.3f}× | {s["cpu_ms_per_query"]:.4f} | {(s["cpu_ms_per_query"]/base["cpu_ms_per_query"]-1)*100:+.2f}% |')
scope='''The native DocID cache accelerates repeated numeric ID-to-row lookup; the separate docstore cache reuses decoded stored-field blocks. This PR now includes the latest opt-in adaptive docstore implementation. Reader registration and lookup remain unchanged; reader TLS is independent in [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045).

| Cache | Setting | Default | Behavior |
| --- | --- | --- | --- |
| Native DocID → RowID | `docid_lookup_cache_size` | `0` | Immutable per-disk-chunk lookup caches; compressed fallback when refused or inapplicable |
| Decoded stored-field blocks | `docstore_cache_size` | `16m` | Shared LRU partitions using seeded XXH3-64 |
| Adaptive block policy | `docstore_cache_adaptive` | `0` | Second-touch admission, gradual cold-entry reclamation, mapped payload storage |

The native DocID cache retains the existing disk format and costs about 11.58 MiB per million entries on the tested hosts; allocation/alignment padding count against its own budget. Chunk remap/destruction releases it. The two cache budgets are independent and server-wide.

The block cache has up to 16 independently locked partitions. A successful lookup/insertion pins the payload; releasing that pin is an atomic decrement, avoiding a second hash lookup and mutex acquisition per returned row. LRU membership and eviction remain locked. Adaptive misses use one fixed 256 KiB atomic fingerprint history: the first visit decodes temporarily, and a repeated fingerprint visit becomes eligible for insertion. Full-key checks preserve correctness despite fingerprint collisions. This reduces first-visit insertion/eviction work without a separate global bypass state.'''
method=f'''Every performance column below uses **the same cache implementation and binary, `{main['source_commit'][:7]}`**, with native DocID caching and SQL query caching disabled and **no reader TLS**. Published head `{identity['published_commit'][:7]}` changes only CMake test registration; production source is byte-identical. These are cache-configuration comparisons, not full-PR speedups over upstream or comparisons against an early PR implementation.

Apple M4 Pro / Clang 21, `-O2 -DNDEBUG`; eight clients and eight workers; 256 returned rows/query, 128-byte stored text, 16 KiB/LZ4. Random queries reuse 64 deterministic templates per client; each sample warms the complete pool. Six balanced rounds × five seconds/arm; reported QPS and server CPU/query are per-arm medians. All nonzero capacities in this matrix use 16 partitions.

**Multiplier = enabled-cache QPS / cache-off QPS in the same case.** 1.30× means 30% more throughput; 0.90× means 10% less. Lower server CPU/query is better.'''
capacity=f'''## 1. Larger budgets extend the useful working-set range

{method}

QPS (multiplier versus cache off):

{qtable()}

Server CPU milliseconds/query:

{ctable()}

![Capacity, throughput and CPU/query](capacity.png)

At 20k–100k rows, 16 MiB already covers most reused blocks; allocating a higher ceiling adds little. At 1M, adaptive 16 MiB gives **{ratio(1000000,'adaptive16'):.2f}×**, while 128/512 MiB give **{ratio(1000000,'adaptive128'):.2f}× / {ratio(1000000,'adaptive512'):.2f}×**. At 5M, adaptive 512 MiB gives **{ratio(5000000,'adaptive512'):.2f}×** and **{delta(5000000,'adaptive512'):+.2f}% CPU/query** versus off. The sampled benefit is not monotonic in total rows: capacity should follow the active **decoded, reused** working set, rather than compressed table size. The plot shows sampled configurations, not an exact crossover or universal optimum. Raising the ceiling and changing admission policy are separate comparisons; manual/adaptive columns at the same ceiling keep that distinction visible.'''
oversize=f'''## 2. Beyond capacity: reduce churn, retain the remaining losses

At 20M random rows, adaptive 512 MiB achieves **{ratio(20000000,'adaptive512'):.3f}×** cache-off throughput ({(ratio(20000000,'adaptive512')-1)*100:+.2f}%), with **{delta(20000000,'adaptive512'):+.2f}% CPU/query**. The same-ceiling manual 512 MiB result is **{ratio(20000000,'manual512'):.3f}×**. Admission filters first visits; it does not eliminate cache lookup, synchronization, temporary decoding or repeated-visit costs.

{chr(10).join(st)}

The advancing scan generates new contiguous 256-ID ranges rather than cycling the random query pool. Its results are a separate locality control. Adaptive mode does **not** guarantee cache-off parity: at 1M random rows with only 16 MiB, throughput is still **{(ratio(1000000,'adaptive16')-1)*100:+.2f}%** versus off. A bigger cache can help when it covers reuse; a low-reuse workload can still favor cache off. There is no automatic low-hit-rate switch to cache off.'''
memory=f'''## 3. A smaller active set releases process memory

Two diagnostic passes retain the same 5M-row table and change only the query access range: **5M broad → 20k hot → 5M broad again**. Each phase runs for eight seconds after warmup. Manual/adaptive order is reversed on the second pass. Values below are medians of the two phase-end snapshots, in MiB; each individual pass and continuous trace is retained.

{chr(10).join(mtable)}

![Broad/hot/broad memory traces, both passes](memory.png)

Both modes allocate on demand; a 512 MiB ceiling never means an eager 512 MiB reservation. Adaptive mode additionally trims cold, unpinned entries after a stable smaller hot set is observed. Decoded payloads use per-partition OS mappings: small blocks are packed into 64 KiB regions, and empty regions are unmapped; larger blocks use dedicated mappings. Up to one empty 64 KiB region is retained per partition (at most 1 MiB total).

Reclamation advances on lookups, not an idle timer. Pinned blocks and partially occupied regions can retain memory. `docstore_cache_size` caps **charged payload allocation classes plus cached entries**, not total mapped bytes or process RSS. Metadata, fingerprint history, reader/result buffers, temporary first-visit decodes and mapping slack are additional; mapping-failure/oversized fallbacks use the process heap. `docstore_cache_used_bytes`, `docstore_cache_mapped_bytes` and `docstore_cache_spare_bytes` expose the separate quantities.'''
validation='''## Configuration and validation

Existing defaults remain manual 16 MiB and native DocID cache off. Opt in explicitly:

```ini
searchd {
    docstore_cache_size = 512m
    docstore_cache_adaptive = 1
}
```

The implementation passes 548 native gtests, API smoke, and DocID lifecycle checks at 0/1 KiB/16 MiB. Thirty focused cache/pool/admission/reclamation tests pass 20 repetitions each under ASan+UBSan and TSan (600 tests per sanitizer). Instrumentation covers docstore, file I/O and the focused test translation unit; other engine archives are reused uninstrumented. ASan leak detection is disabled on macOS. Previously pushed CI repairs remain included: Windows output types, GoogleTest compatibility, smoke/metric expectations and alignment-safe access. The latest follow-up relocates three test registrations to remove the conflict with newly added upstream suites; it preserves the exact registered test-source set.

GitHub reports the updated PR as mergeable. The [upstream test workflow](https://github.com/manticoresoftware/manticoresearch/actions/runs/43545580359), docs and packaging workflows are `action_required`, awaiting maintainer approval for the fork; the test run has zero executed jobs. This is not a CI pass. Linux/Windows CI and production endurance are not established by this macOS measurement. Cache clear/shutdown retain their existing quiescent-reader preconditions.'''
report=f'''# Adaptive docstore cache: capacity, oversized working sets and memory return

{scope}

{capacity}

{oversize}

{memory}

{validation}

## Evidence and reproduction

- [All configuration medians](summary.csv), [all timed samples](all-samples.csv), [memory stage endpoints](memory-stages.csv), and [full tables including controls](TABLES.md).
- `raw/measurement/` preserves the original five-size matrix, two memory passes per mode and telemetry; `raw/confirm-*/` retains complete independent confirmations. `raw/controls/` contains the A/A and advancing scan. No raw round is dropped.
- Source and binary identities are in `source-isolation.json`, `raw/measurement/plan.json` and `summary.json`. The binary SHA-256 is `{main['binary_sha256']}`. `source.patch` is the integration over the preceding published PR commit; `full-pr.patch` is the full source change over the PR base.
- Run `python3 run_final.py --selfcheck`, then `python3 run_final.py`; run `python3 run_controls.py` separately, after the matrix. Fixtures are generated by the archived standard-library driver. The benchmark binary is built separately from the recorded source and must be placed beside the drivers. Large immutable table fixtures and executable binaries are omitted from the archive.
- The pre-recorded repeat rule retains all samples and schedules a complete confirmation when mean external CPU exceeds 10% of machine or a peak exceeds 20%; it never selects individual rounds by performance. Selected cases: `{json.dumps(summary['selected_series'],sort_keys=True)}`. The retained throughput series has {summary['all_timed_samples']} samples and {summary['all_checked_timed_queries']:,} response-checked timed queries; {summary['all_flagged_samples']} samples cross the recorded rule, including originals retained alongside confirmations. Selected random matrix flags: {summary['selected_flagged_samples']}. Memory diagnostics have their own status sampler and are not pooled into throughput results.
- The independent cache-off A/A control gives QPS `{aa['arms']['off-A']['qps']:,.1f}` / `{aa['arms']['off-B']['qps']:,.1f}` ({(aa['arms']['off-B']['qps']/aa['arms']['off-A']['qps']-1)*100:+.2f}%) and CPU/query `{aa['arms']['off-A']['cpu_ms_per_query']:.4f}` / `{aa['arms']['off-B']['cpu_ms_per_query']:.4f}` ms. Sub-percent differences in individual configuration columns should be treated as approximately flat, not established wins.

The finite random pools, structured compressible text and sampled scan locate capacity/locality tradeoffs. They do not establish universal no-regression behavior, automatic optimal sizing, mixed-write throughput, long-duration endurance or adaptive-plus-reader-TLS performance. Native DocID lookup-kernel measurements and historical TLS results are independent evidence; their gains must not be multiplied into these configuration comparisons.
'''
(OUT/'REPORT.md').write_text(report)
(OUT/'PR_BODY_LOCAL.md').write_text(scope+'\n\n'+capacity+'\n\n'+oversize+'\n\n'+memory+'\n\n'+validation+'\n')
print('Wrote English report and PR draft.')
