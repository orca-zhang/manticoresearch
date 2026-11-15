#!/usr/bin/env python3
"""Validate the full journals and render a standalone English TLS-only report."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def pct(value):
    return f'{value:+.2f}%'


def delta(before, after):
    return (after / before - 1) * 100


def validate(data, measurement):
    assert data['completed']
    total, flagged = 0, 0
    for case in data['cases']:
        rows = [json.loads(x) for x in (measurement / (case['case']['name'] + '-samples.jsonl')).read_text().splitlines()]
        assert len(rows) == 2 * data['rounds']
        assert case['lifecycle_passed']
        for label, arm in case['arms'].items():
            raw = [x['sample'] for x in rows if x['arm'] == label]
            assert len(raw) == len(arm['samples']) == data['rounds']
            for a, b in zip(raw, arm['samples']):
                assert all(b[k] == v for k, v in a.items())
                assert a['completed'] > 0 and a['elapsed_seconds'] >= data['seconds_per_arm']
                total += a['completed']
                flagged += b['quality_flag']
            for metric in ('qps', 'server_cpu_ms_per_query'):
                assert statistics.median(s[metric] for s in raw) == arm[metric + '_median']
        a, b = [case['arms'][x] for x in ('baseline', 'tls')]
        assert delta(a['qps_median'], b['qps_median']) == case['qps_change_percent']
        assert delta(a['server_cpu_ms_per_query_median'], b['server_cpu_ms_per_query_median']) == case['cpu_change_percent']
        if case['case'].get('aa'):
            assert a['binary'] == b['binary'] == 'searchd-baseline'
        else:
            assert (a['binary'], b['binary']) == ('searchd-baseline', 'searchd-tls')
    return total, flagged


def name(case):
    c = case['case']
    if c.get('aa'):
        return 'A/A, 256 rows (same upstream binary)'
    if c.get('count'):
        return 'Count only, 256 IDs'
    if c.get('mixed'):
        return '4 bulk clients + 4 hot point clients'
    return f"Random, {c['batch']} stored row{'s' if c['batch'] != 1 else ''}"


def table(cases):
    text = ['| Rows | Workload | Cache | Upstream QPS | TLS QPS | QPS change | CPU/query: upstream → TLS (ms) | CPU change |',
            '| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for case in cases:
        c = case['case']
        a, b = [case['arms'][x] for x in ('baseline', 'tls')]
        text.append(f"| {c['rows']:,} | {name(case)} | {c['cache_mib']} MiB | {a['qps_median']:,.0f} | {b['qps_median']:,.0f} | {pct(case['qps_change_percent'])} | {a['server_cpu_ms_per_query_median']:.4f} → {b['server_cpu_ms_per_query_median']:.4f} | {pct(case['cpu_change_percent'])} |")
    return '\n'.join(text)


def plot(primary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.7))
    for cache, color, marker in ((16, '#2866a6', 'o'), (0, '#bd671d', 's')):
        selected = sorted((x for x in primary if x['case']['cache_mib'] == cache), key=lambda x: x['case']['rows'])
        for axis, key, paired, title in zip(axes, ('qps_change_percent', 'cpu_change_percent'),
                                            ('paired_qps_changes_percent', 'paired_cpu_changes_percent'),
                                            ('QPS change (higher is better)', 'Server CPU/query change (lower is better)')):
            xs = [x['case']['rows'] for x in selected]
            ys = [x[key] for x in selected]
            axis.plot(xs, ys, marker=marker, color=color, label=f'{cache} MiB block cache')
            for x, y, row in zip(xs, ys, selected):
                axis.vlines(x, min(row[paired]), max(row[paired]), color=color, alpha=.55)
                offset = 9 if cache == 0 else -16
                if key == 'cpu_change_percent' and x == 1000000:
                    offset = -16 if cache == 0 else 9
                axis.annotate(f'{y:+.2f}%', (x, y), xytext=(0, offset),
                              textcoords='offset points', ha='center', fontsize=9, color=color)
            axis.set_title(title, fontsize=11)
            axis.set_xscale('log')
            axis.set_xticks([20000, 1000000, 10000000], ['20k', '1M', '10M'])
            axis.set_xlabel('Table rows (log scale)')
            axis.set_ylabel('TLS vs upstream (%)')
            axis.axhline(0, color='gray', linewidth=.8, linestyle='--')
            axis.grid(alpha=.18)
            axis.margins(x=.15, y=.22)
            axis.legend(fontsize=9)
    fig.suptitle('PR #5045: reader TLS only, original upstream block cache in both arms', fontsize=12)
    fig.text(.5, .015, '8 clients • 256 stored rows/query • 6 alternating rounds × 5 s/arm\nPoints: ratio of medians. Whiskers: min–max of the six paired changes; not confidence intervals.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .94))
    fig.savefig(output / 'reader-tls-independent.png', dpi=180)
    fig.savefig(output / 'reader-tls-independent.svg')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('measurement', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--no-plot', action='store_true')
    parser.add_argument('--repeat', type=Path)
    args = parser.parse_args()
    data = json.loads((args.measurement / 'results.json').read_text())
    total, flagged = validate(data, args.measurement)
    repeat = json.loads((args.repeat / 'results.json').read_text()) if args.repeat else None
    if repeat:
        repeat_total, repeat_flagged = validate(repeat, args.repeat)
        assert repeat['binary_sha256'] == data['binary_sha256']
        assert len(repeat['cases']) == 1
        original = next(x for x in data['cases'] if x['case']['name'] == repeat['cases'][0]['case']['name'])
        assert original['query_sha256'] == repeat['cases'][0]['query_sha256']
    args.output.mkdir(parents=True, exist_ok=True)
    primary = [x for x in data['cases'] if x['case']['name'].startswith('random256')]
    other = [x for x in data['cases'] if x not in primary]
    lookup = {x['case']['name']: x for x in data['cases']}
    small_on, small_off = [lookup[f'random256-20000-{c}m'] for c in (16, 0)]
    on = [x['qps_change_percent'] for x in primary if x['case']['cache_mib'] == 16]
    off = [x['qps_change_percent'] for x in primary if x['case']['cache_mib'] == 0]
    aa = [x for x in other if x['case'].get('aa')]
    mixed = [x for x in other if x['case'].get('mixed')]
    samples = sum(len(a['samples']) for x in data['cases'] for a in x['arms'].values())
    text = f'''# PR #5045: independent reader TLS benchmark — 2026-11-14

This experiment measures **only the reader TLS change in PR #5045**. Both arms use the original upstream single-lock, CRC32-based docstore block cache. No #5042 shared-cache sharding, XXH3 change, native DocID cache, adaptive admission, private block pinning or mapped-allocation experiment is included.

For the 256-row workload, the default 16 MiB cache produces TLS QPS changes from **{pct(min(on))} to {pct(max(on))}** across 20k, 1M and 10M rows. With the block cache disabled, the corresponding range is **{pct(min(off))} to {pct(max(off))}**. At 20k rows, cache-off TLS changes QPS by **{pct(small_off['qps_change_percent'])}** and server CPU/query by **{pct(small_off['cpu_change_percent'])}**; the default-cache changes are **{pct(small_on['qps_change_percent'])}** and **{pct(small_on['cpu_change_percent'])}**. These results do not establish a general default-cache throughput improvement or a gain that increases monotonically with table size.

## Source and build isolation

| Arm | Production source |
| --- | --- |
| Upstream | `047d2f99522d78e0aa1de7e7dc945a9abe1b673a` |
| TLS | The same source plus the exact `src/docstore.cpp` diff from `019868e9f79d1bb2bd1f96dafb88ef20acd45418` |

The five PR reader tests and their CMake registration were added identically to both arms. Both builds used the same worktree revision and generated version headers. **Only `src/CMakeFiles/lmanticore.dir/docstore.cpp.o` changed out of 299 object files**; the complete before/after SHA-256 lists and unchanged LRU source hashes are included in the evidence. The production patch is 27 changed lines in one source file. MCL was configured API-only in both builds; the workloads use the rowwise engine.

Binary SHA-256:

```text
upstream {data['binary_sha256']['baseline']}
TLS      {data['binary_sha256']['tls']}
```

## Method

- Apple M4 Pro, 12 CPU cores, 24 GiB RAM, ARM64 macOS, Apple Clang 21.0.0; `-O2 -DNDEBUG`, identical compiler and link options.
- 20,000, 1,000,000 and 10,000,000 rows. One deterministic 128-byte stored-only text field; 16 KiB docstore blocks, LZ4 compression, flushed disk chunks. This is stored-field retrieval, not full-text search.
- Eight concurrent clients and eight server threads over loopback HTTP keep-alive. Deterministic random IDs, exact response validation on every query, SQL query-result cache disabled. Native DocID caching is absent from this upstream source; no DocID-cache configuration was injected.
- Same original block-cache implementation and capacity within each pair: either default 16 MiB or explicitly 0. The reader buffer budget remains 8 MiB in both arms.
- Six rounds per case, five timed seconds per arm, balanced alternating AB/BA order. Only one arm receives benchmark traffic at a time. Each worker warms its complete fixed query pool before each timed interval; pool sizes and query hashes are in the raw results. OS file pages are warm; this is not a cold-storage benchmark.
- A 30-second pre-case idle gate and continuous one-second telemetry are retained. All **{samples} timed samples / {total:,} completed, validated timed queries** are included. Telemetry flags: **{flagged}**. No rounds were selected or removed by their QPS.
- QPS is completed queries divided by elapsed wall time. CPU/query uses the server process user+system CPU delta divided by completed queries, excluding clients and warm-up. Values in the tables are per-arm medians; percentages compare those medians. Negative CPU change means less CPU per query. Mixed-workload aggregate QPS depends on the work mix; its two groups are also reported.

HTTP keep-alive does not retain a docstore session across queries: stored-field materialization uses query-scoped `DocstoreSession_c` instances. Point and mixed cases therefore exercise session creation/cleanup and cross-thread generation invalidation, while bulk cases offer more reader reuse inside a session.

## Scale comparison: 256 stored rows per query

{table(primary)}

![Independent TLS effect by table size](reader-tls-independent.png)

The plot samples three table sizes; it does not locate a universal optimum between those points. Whiskers show the six paired percentage changes, not a confidence interval. Raw decompressed payload sizes are approximately 2.44 MiB, 122.07 MiB and 1.19 GiB, respectively, before docstore metadata. Compressed `.spds` sizes are recorded separately in the evidence. Total rows, compressed file bytes, decoded cache capacity and active working set are different quantities.

## Smaller results, session churn and controls

{table(other)}

In the A/A cases, both labels execute the **same upstream binary**, so their differences estimate run-to-run variation rather than a TLS effect. The count-only case does not retrieve stored text. Small percentage differences should be read alongside these controls and the six paired samples; a positive sign alone is not evidence of a reliable improvement.

### Mixed workload groups

Four clients retrieve 256 random stored rows; four retrieve one stored row from the first 4,096 IDs. Group QPS is reported because a change in the relative completion rate can alter aggregate QPS and CPU/query.

| Block cache | Bulk QPS: upstream → TLS | Bulk change | Point QPS: upstream → TLS | Point change |
| ---: | ---: | ---: | ---: | ---: |
'''
    for case in mixed:
        a, b = [case['arms'][x] for x in ('baseline', 'tls')]
        text += f"| {case['case']['cache_mib']} MiB | {a['bulk_qps_median']:,.0f} → {b['bulk_qps_median']:,.0f} | {pct(delta(a['bulk_qps_median'], b['bulk_qps_median']))} | {a['point_qps_median']:,.0f} → {b['point_qps_median']:,.0f} | {pct(delta(a['point_qps_median'], b['point_qps_median']))} |\n"
    if repeat:
        row = repeat['cases'][0]
        text += f'''
### Complete verification repeat

The predeclared telemetry rule triggered a complete repeat of the 20k-row, cache-off, 64-row query comparison. The original six rounds remain in the main table and evidence. No individual round was removed or substituted. The additional six-round pair has **{repeat_flagged}** telemetry flags and **{repeat_total:,}** validated timed queries. It measured QPS **{pct(row['qps_change_percent'])}** and CPU/query **{pct(row['cpu_change_percent'])}**, using the same binary hashes and identical query-pool hash. The evidence includes both preregistered plans and all **{samples + 2 * repeat['rounds']}** timed samples across the main matrix and repeat.

{table(repeat['cases'])}

'''
    text += '''
## Why the effect changes

`ReadDocFromSmallBlock()` first looks up an already decoded block. On a block-cache hit, it skips `UncompressSmallBlock()` and `ReadFromFile()`, so it never reaches the reader lookup optimized by this PR. On a miss, `ReadFromFile()` calls `DocstoreReaders_c::GetReader()`; TLS can avoid its registry mutex for repeated access to the same session/index while the generation stays unchanged. Cache-off bulk retrieval exposes this path much more frequently.

Larger tables do not automatically create a larger TLS benefit. Reader lookup is only one part of a query; ID resolution, parsing, response serialization, decompression and the original shared block-cache mutex still cost time. Concurrent session creation/deletion increments the global generation, which can invalidate a thread's one-entry TLS cache. This experiment measures their combined end-to-end effect rather than attributing every percentage change to a particular hardware bottleneck. No TLS hit counters or profiler instrumentation were added to the timed binaries.

Increasing the block-cache capacity changes the experiment and may improve the hit rate for a particular workload. A higher hit rate also skips more reader lookups, which can reduce the incremental TLS benefit. These tables compare TLS at equal cache capacity; cache-on versus cache-off absolute QPS must not be relabeled as a TLS gain or combined with #5042 gains.

## Correctness and limits

- Both arms passed all 496 native gtests in isolated working directories.
- All five reader lifetime/invalidation/concurrency tests passed a further 20 repetitions in each arm (100 test executions per arm).
- Existing fixtures were smoke-checked at all three sizes in both binaries, including row counts and exact first/middle/last stored values.
- Every measured case passed REPLACE, FLUSH and DROP/recreate checks after timing, in both arms.
- TLS retains a borrowed reader pointer, not ownership. The generation detects invalidation; it does not make concurrent destruction during active pointer use safe. Existing session/index lifetime rules and quiescent registry shutdown remain required. The tests respect those rules.
- This is one Apple ARM64 host with eight clients, short warm runs and one synthetic text layout. No fresh Linux/x86 run, cold-disk benchmark, >8-client saturation study or sanitizer build was performed for this measurement. The full paired samples and A/A controls are retained; these results are not a guarantee for every workload.

## Reproduction and evidence

The evidence archive contains the exact TLS production patch; common reader tests; build configuration and compile commands; object and binary hashes; native-test logs; benchmark/report drivers; the preregistered case plan; complete result JSON; per-sample journals; load telemetry; and CSV exports. The fixtures are deterministic and can be rebuilt with `benchmark.make_fixture()` before running the driver.

```sh
python3 driver/run_tls.py --selfcheck
python3 driver/run_tls.py --fixtures /path/to/fixtures --output measurement --rounds 6 --duration 5
python3 driver/run_tls.py --fixtures /path/to/fixtures --output repeat64 --cases random64-20000-0m --rounds 6 --duration 5
python3 driver/make_report.py measurement report --repeat repeat64
```

`run_tls.py` expects `searchd-baseline`, `searchd-tls` and `calibration.json` beside its `driver` directory. Build commands and base/source identities are preserved with the evidence. Plot regeneration requires Matplotlib; the benchmark itself uses the Python standard library only.
'''
    (args.output / 'REPORT.md').write_text(text)
    with (args.output / 'summary.csv').open('w') as f:
        writer = csv.writer(f)
        writer.writerow(['phase', 'case', 'rows', 'cache_mib', 'workload', 'baseline_qps', 'tls_qps', 'qps_change_percent',
                         'baseline_cpu_ms_per_query', 'tls_cpu_ms_per_query', 'cpu_change_percent'])
        for phase, dataset in [('main', data)] + ([('repeat64', repeat)] if repeat else []):
            for case in dataset['cases']:
                c = case['case']; a, b = [case['arms'][x] for x in ('baseline', 'tls')]
                writer.writerow([phase, c['name'], c['rows'], c['cache_mib'], name(case), a['qps_median'], b['qps_median'],
                                 case['qps_change_percent'], a['server_cpu_ms_per_query_median'], b['server_cpu_ms_per_query_median'], case['cpu_change_percent']])
    with (args.output / 'samples.csv').open('w') as f:
        writer = csv.writer(f)
        writer.writerow(['phase', 'case', 'arm', 'round', 'qps', 'server_cpu_ms_per_query', 'completed', 'elapsed_seconds', 'quality_flag'])
        for phase, dataset in [('main', data)] + ([('repeat64', repeat)] if repeat else []):
            for case in dataset['cases']:
                for label, arm in case['arms'].items():
                    for s in arm['samples']:
                        writer.writerow([phase, case['case']['name'], label, s['round'], s['qps'], s['server_cpu_ms_per_query'],
                                         s['completed'], s['elapsed_seconds'], s['quality_flag']])
    if not args.no_plot:
        plot(primary, args.output)
    print(json.dumps({'timed_samples': samples, 'validated_timed_queries': total, 'quality_flags': flagged}))


if __name__ == '__main__':
    main()
