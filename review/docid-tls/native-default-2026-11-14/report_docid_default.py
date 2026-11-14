#!/usr/bin/env python3
"""Render the isolated default-admission study without modifying raw samples."""
import csv
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'docid-default-report-20261114'


def main():
    primary = json.loads((ROOT / 'docid-default-20261114/results.json').read_text())
    large = json.loads((ROOT / 'docid-default-large-20261114/results.json').read_text())
    assert len(primary['cases']) == 7 and len(large['cases']) == 2 and large['completed']
    assert primary['source_commit'] == large['source_commit']
    assert primary['binary_sha256'] == large['binary_sha256']
    r = dict(primary, cases=primary['cases'] + large['cases'], completed=True,
             provenance=['docid-default-20261114/results.json', 'docid-default-large-20261114/results.json'])
    confirmation = json.loads((ROOT / 'docid-count-confirmation-20261114/results.json').read_text())
    assert confirmation['completed'] and confirmation['binary_sha256'] == r['binary_sha256']
    assert all(len(a['samples']) == 6 for c in r['cases'] for a in c['arms'].values())
    OUT.mkdir(exist_ok=True)
    (OUT / 'results.json').write_text(json.dumps(r, indent=2) + '\n')
    labels = {'stored': '256 IDs + stored body', 'id-only': '256 IDs, ID only',
              'point': 'Single ID', 'full-count': 'Full count (no ID filter)'}
    rows = []
    for c in r['cases']:
        a, b = c['arms']['off'], c['arms']['default']
        paired = [y['qps'] / x['qps'] for x, y in zip(a['samples'], b['samples'])]
        rows.append(dict(rows=c['rows'], workload=c['workload'],
            qps_off=a['qps'], qps_default=b['qps'], qps_ratio=b['qps']/a['qps'],
            cpu_ms_off=a['cpu_ms_per_query'], cpu_ms_default=b['cpu_ms_per_query'],
            cpu_change_percent=(b['cpu_ms_per_query']/a['cpu_ms_per_query']-1)*100,
            native_mib=b['docid_used_bytes']/2**20,
            paired_ratio_min=min(paired), paired_ratio_max=max(paired),
            flagged_samples=sum(s['quality_flag'] for v in c['arms'].values() for s in v['samples'])))
    with (OUT / 'summary.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = ['| Rows | Workload | QPS off → default | QPS ratio | CPU ms/query off → default | CPU change | Native MiB |',
             '| ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for d in rows:
        table.append(f"| {d['rows']:,} | {labels[d['workload']]} | {d['qps_off']:,.1f} → {d['qps_default']:,.1f} | {d['qps_ratio']:.3f}× | {d['cpu_ms_off']:.4f} → {d['cpu_ms_default']:.4f} | {d['cpu_change_percent']:+.2f}% | {d['native_mib']:.2f} |")
    (OUT / 'table.md').write_text('\n'.join(table) + '\n')
    flags = sum(d['flagged_samples'] for d in rows)
    samples = [s for c in r['cases'] for arm in c['arms'].values() for s in arm['samples']]
    lines = ['# Native DocID lookup: default demand admission', '',
        '## Requirement and implementation', '',
        'Repeated sparse numeric ID batches can spend substantial CPU decoding the compressed disk lookup. A native immutable mapping provides contiguous keys, a cache-line directory and 16 interleaved probes. A complete mapping also lets the planner bound sparse results by the number of input IDs, including the lookup cost of misses.', '',
        '`docid_lookup_cache_size` remains the sole setting: default `64m`, with `0` disabling it. It is a process-wide allocation ceiling, with whole-chunk admission. Loading chunks, scalar lookups, dense lists and full-count queries do not construct mappings. The first eligible batch records demand; subsequent eligible planning/update calls decode at most 16,384 entries each. Eligibility requires at least 16 numeric IDs and at most 1/64 of chunk rows. The final call also seals the directory.', '',
        'One builder advances through an atomic state transition; overlapping callers use the compressed path without waiting. Only a sealed unique-ID mapping is published through an acquire/release pointer. Scalar `Find` retains the compressed path without a cache-pointer branch. Allocation failure, exhausted budget, duplicates and interruption preserve the original lookup. Both incomplete and completed allocations are charged to the ceiling and released on chunk remap/destruction. Refused chunks wait until remap before retrying; allocations have no idle shrinking or hot-entry eviction. No reader TLS is used.', '',
        '## Isolated latest-binary comparison', '',
        f"Source: `{r['source_commit']}`. Binary SHA-256: `{r['binary_sha256']}`. The maintained PR head was merged before measuring. Both arms use this same binary; only native DocID configuration changes: explicit `0` versus omitted setting (default 64 MiB). Both keep adaptive docstore at 16 MiB, SQL query cache at zero, and reader TLS absent. These are configuration comparisons, not full-PR speedups over upstream.", '',
        'Apple M4 Pro / Clang 21, `-O2 -DNDEBUG`; eight clients and eight server workers. Each client cycles 64 deterministic query templates, with full warmup before every timed sample. Six balanced AB/BA rounds × five seconds per arm. Every timed response is checked. Batch queries return 256 rows; stored bodies have 128 bytes, with 16 KiB/LZ4 blocks. Single-ID queries use `id IN (<one>)` and return ID only. Full count has no ID filter. Every case starts fresh servers, so point/count controls have no mapping left from an earlier batch test. A 512-request serial cold pass completes admitted construction before steady-state timing.', '',
        'The 20k/1M/5M/20M fixtures contain 1/3/9/26 disk chunks respectively; the per-chunk row counts are preserved in `docid-fixture-manifest.json`. No OPTIMIZE was forced to merge them into one chunk. Eligibility and construction apply per chunk. The 16K decoding limit is per eligible build call; a query visiting several chunks can advance several builders. Scale comparisons include the changing chunk layout.', '',
        'QPS and server CPU/query below are per-arm medians; ratio = default QPS / off QPS. Lower CPU/query is better.', '',
        *table, '', '![Native default-on throughput and CPU](native-default.png)', '',
        'At 20M rows, all chunk mappings together exceed the default 64 MiB budget. Some chunks are admitted and the others retain compressed lookup. This tests partial admission and fallback under the default ceiling; it does not measure a larger native budget. Native allocations are additional to the independent docstore cache. Construction and startup are excluded from the steady-state table.', '',
        'Paired-round ratio ranges describe variation, not confidence intervals:', '',
        '| Rows | Workload | Minimum → maximum QPS ratio |', '| ---: | --- | ---: |']
    for d in rows:
        lines.append(f"| {d['rows']:,} | {labels[d['workload']]} | {d['paired_ratio_min']:.3f}× → {d['paired_ratio_max']:.3f}× |")
    lines += ['', '## Fresh-process count confirmation', '',
        'The primary full-count control showed a negative point estimate despite both arms allocating zero native cache bytes. A separate confirmation starts fresh servers in reversed order (default first, then off), and adds an explicit `64m` arm to distinguish the omitted default from an explicit budget. All six permutations of the three timed arms are used once. The same eight clients, five-second samples, query pool and idle/quality gates apply. No primary result is replaced.', '',
        '| Native setting | QPS | QPS / off | Server CPU ms/query | CPU vs off |',
        '| --- | ---: | ---: | ---: | ---: |']
    off = confirmation['arms']['off']
    for label, a in confirmation['arms'].items():
        lines.append(f"| {label} | {a['qps']:,.1f} | {a['qps']/off['qps']:.3f}× | {a['cpu_ms_per_query']:.4f} | {(a['cpu_ms_per_query']/off['cpu_ms_per_query']-1)*100:+.2f}% |")
    conf_samples = [s for a in confirmation['arms'].values() for s in a['samples']]
    lines += ['', f"Every confirmation sample allocated zero native cache bytes. Quality flags: {sum(s['quality_flag'] for s in conf_samples)}. Small differences in this control do not establish a universal speedup or a causal cache cost; the count query does not build a mapping. Raw samples and configurations are retained."]
    lines += ['', '## Cold construction diagnostic', '',
        'Each arm executes the same 512 requests serially before parallel timing. All individual latencies and server CPU totals are preserved in `results.json`. This is one diagnostic pass per arm, with no paired repetition; it is not a production tail-latency estimate or a hard latency bound. Decoded work is limited per builder call, while allocation/page faults and final directory sealing can still add latency.', '',
        '| Rows | ID-only arm | 512-request wall time ms | Server CPU ms | p50 ms | p95 ms | Maximum ms |',
        '| ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for c in r['cases']:
        if c['workload'] != 'id-only' or c['rows'] not in (1000000, 5000000):
            continue
        for label, a in c['arms'].items():
            d = a['cold']
            lines.append(f"| {c['rows']:,} | {label} | {d['total_ms']:.1f} | {d['cpu_ms']:.1f} | {d['p50_ms']:.3f} | {d['p95_ms']:.3f} | {d['max_ms']:.3f} |")
    lines += ['', '## Validation and evidence', '',
        'The merged production code passed 577 native tests, with 17 additional tests skipped for platform/feature conditions, API smoke, four native lifecycle configurations (default, zero, refused, admitted), and all six docstore switch cases. The final test-only scheduling correction passed focused tests and 23 native cache/lookup tests ×20 under ASan+UBSan and TSan (460 per sanitizer). Instrumentation covers the cache, lookup and their two test translation units; other engine libraries are reused without instrumentation. ASan leak detection is disabled on macOS. The first sanitizer attempt exposed an overly strict test completion assumption; its log is retained. Nonblocking calls can skip construction while another caller builds, so the test now finishes remaining steps serially before asserting readiness.', '',
        f"Main matrix: {len(samples)} timed samples, {sum(s['completed'] for s in samples):,} checked timed queries, {flags} load-quality flags. Count confirmation adds {len(conf_samples)} samples and {sum(s['completed'] for s in conf_samples):,} checked queries, with zero flags. The idle gate requires 30 seconds with mean system idle ≥90% and minimum ≥80%. Mean external CPU >10% machine or peak >20% flags a sample. All samples and telemetry are retained; flags require complete-case confirmation.", '',
        'The published follow-up `a1dd0db409e2365cf372a13c18cdc1cb72a6b029` changes documentation only; its production sources match the measured commit. Its upstream CI workflows require maintainer approval (`action_required`). The preceding merged head built successfully on its tested platforms but failed one CLT columnar REPLACE timing-ratio assertion: 13 against an allowed maximum of 12. That public job log is archived; the threshold is unchanged here. These local passes do not establish an all-green upstream CI run.', '',
        'Files: original plans/results (including configs, SQL plans, cold traces and raw timing), per-case JSONL journals and load telemetry, combined `results.json`, `summary.csv`, and the exact benchmark/render scripts. The primary driver completed seven cases, then stopped before 20M timing because its assertion incorrectly assumed one oversized chunk. A separate continuation corrects only that multi-chunk admission expectation and measures the two remaining cases using the same binary/protocol. The seven completed cases are preserved without rerunning or selecting rounds. Historical pre-optimization measurements and the interrupted pre-upstream attempt are archived separately; neither is substituted for the table above.', '',
        'These are warm synthetic ID-filter workloads on macOS. Linux/Windows performance, production endurance, sparse updates and full-text combinations are not established by this throughput matrix. Correctness checks cover updates and planner behavior separately. Cache remap/destruction retains the owning chunk’s quiescent-reader lifetime requirement.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    records = [dict(case=c['name'], arm=label, round=s['round']+1,
                    **{k: s[k] for k in ('qps', 'cpu_ms_per_query', 'p95_ms', 'rss_bytes',
                                         'docid_used_bytes', 'completed', 'quality_flag')})
               for c in r['cases'] + [dict(name='count-confirmation', arms=confirmation['arms'])]
               for label, arm in c['arms'].items() for s in arm['samples']]
    with (OUT / 'all-samples.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    for kind, label, marker in [('id-only', '256 IDs, ID only', 'o'), ('stored', '256 IDs + stored body', 's')]:
        points = [d for d in rows if d['workload'] == kind]
        x = [d['rows'] for d in points]
        axes[0].plot(x, [d['qps_ratio'] for d in points], marker=marker, label=label)
        axes[1].plot(x, [-d['cpu_change_percent'] for d in points], marker=marker, label=label)
    for ax in axes:
        ax.set_xscale('log')
        ax.set_xticks([20000, 1000000, 5000000, 20000000], ['20k', '1M', '5M', '20M'])
        ax.set_xlabel('Table rows (1 / 3 / 9 / 26 disk chunks)')
        ax.grid(alpha=.25)
        ax.legend(fontsize=8, loc='best')
    axes[0].axhline(1, color='gray', linestyle='--', linewidth=1)
    axes[0].set_ylabel('QPS / native cache off (×)')
    axes[0].set_title('Batch throughput at the default 64 MiB ceiling')
    axes[1].axhline(0, color='gray', linestyle='--', linewidth=1)
    axes[1].set_ylabel('Server CPU/query reduction (%)')
    axes[1].set_title('CPU savings depend on admitted mappings')
    fig.suptitle('Native DocID cache: demand-built by default\nSame binary; adaptive docstore fixed at 16 MiB; no reader TLS', fontsize=11)
    for extension in ('png', 'svg'):
        fig.savefig(OUT / ('native-default.' + extension), dpi=170)
    plt.close(fig)
    print('\n'.join(table))
    print('Quality flags:', flags)


if __name__ == '__main__':
    main()
