from pathlib import Path
import json
r=Path('/private/tmp/manticore-adaptive-cache-review-20261113')
p=Path('/private/tmp/manticore-block-cache-evidence-20261113/review/docid-tls')
d=json.loads((r/'summary.json').read_text());raw=json.loads((r/'sql/matrix.json').read_text())
parts=[]
def add(s):parts.append(s.strip()+'\n')
def table(headers,rows):
 add('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(str(v) for v in row)+' |' for row in rows))
def f(n):return f'{n:,.1f}'
def pct(n):return f'{n:+.2f}%'
add('''# Adaptive docstore block-cache experiment — 2026-11-13

The opt-in prototype can release cold cache entries when an active workload
contracts and refill them when it expands. **It did not reduce process RSS in
either memory-transition pass.** At an equal 512 MiB ceiling, steady-workload
QPS changes range from -0.40% to +1.23%, with both signs and substantial
individual-round variation. No consistent extra throughput benefit is established.

Raising the manual cache ceiling from 16 to 512 MiB is a separate capacity
change: it improves QPS by 87.37%, 76.59% and 37.67% at 500k, 1M and 5M rows
for these query pools. Those gains do not come from the adaptive policy.
The strongest sampled capacity benefit is at 500k, not at the largest dataset.

Status: **experimental follow-up, not included in either production PR**.
[#5042](https://github.com/manticoresoftware/manticoresearch/pull/5042) remains
`376fbf9988b2458ee196a5d92135c35a5121edc7`, with no reader TLS.
[#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045) remains
TLS-only at `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
The experiment is [source commit ad885be366eda4e897c828f05cb93ff04702d02c](https://github.com/orca-zhang/manticoresearch/commit/ad885be366eda4e897c828f05cb93ff04702d02c),
based on #5042. No adaptive-plus-reader-TLS measurement exists.

[Raw samples, plans, snapshots and validation logs](evidence/2026-11-13/adaptive-cache/),
[derived CSV](evidence/2026-11-13/adaptive-cache/summary.csv),
[final experimental patch](evidence/2026-11-13/adaptive-cache/final-validation/adaptive-cache-final.patch),
[download experiment evidence](attachments/adaptive-cache-evidence.zip).
The earlier [0/8/16 MiB and TLS budget report](BLOCK_CACHE_BUDGETS_2026-11-13.md)
remains a separate phase with its original samples and archive.

## What is adaptive here

The existing LRU already allocates on demand. A `512m` setting is a ceiling,
not a reservation: at 20k rows, manual 16 MiB, manual 512 MiB and adaptive
512 MiB all retain only **2.509 MiB** of charged cache entries. Raising the
ceiling alone already allows demand growth without allocating unused capacity.

The prototype adds opt-in cold-entry reclamation after a smaller hot set is
observed. Existing defaults remain `docstore_cache_size=16m` and
`docstore_cache_adaptive=0`. An explicit experimental configuration is:

```ini
searchd {
    # Other required searchd settings omitted.
    docstore_cache_size = 512m
    docstore_cache_adaptive = 1
}
```

The limit covers decoded cached payload plus LRU entries, not total process
memory. Hash tables, allocator overhead, reader buffers, other engine state and
in-flight decompression are additional. Allocation failure behavior is unchanged.
The policy does not raise the configured ceiling, resize shard mappings, add
TLS, or bypass an inefficient low-hit-rate cache.

Each shard uses its existing mutex and a local access epoch. After four
4096-lookup windows with at least 99% hits and touched bytes below one quarter
of retained bytes, it targets twice the recently touched bytes, with a floor
of up to 16 MiB across shards. Every 64 lookups it examines at most 32 tail
entries. Referenced entries and entries touched in the current or previous
epoch survive. Normal admission can grow again to the hard entry ceiling.
The floor is a target, not a minimum allocation or guaranteed final occupancy;
the activity threshold and pinned entries can stop reclamation above it.

Reclamation is lookup-driven. Fully idle shards do not advance epochs, and
there is no wall-clock idle trim. Low-hit-rate workloads keep normal LRU
admission/eviction. There is no process-global generation counter or atomic
update on this path. The shared cache retains seeded **XXH3-64**.

`SHOW STATUS LIKE 'docstore_cache_used_bytes'` reports charged entry bytes,
summed from separately locked shard snapshots. It is neither process RSS nor
an atomic snapshot across all shards. Production-rate monitoring overhead was
not benchmarked; this study polls it between primary timed samples and during
a separate diagnostic.

## Preselected measurement design

The [plan](evidence/2026-11-13/adaptive-cache/measurement-plan.json) was saved
before results. Apple M4 Pro, Clang 21 `-O2 -DNDEBUG`, rowwise 128-byte text,
16 KiB/LZ4 blocks, eight clients and eight query workers, 256 returned rows,
persistent HTTP, an 8 MiB reader-buffer budget. Native DocID and SQL query
caches are both disabled. There is no reader TLS in any arm.

All arms use the same fixtures and deterministic seed-513 query pools: eight
clients each cycle through 20 random 256-ID queries. Each client warms its
pool before each timed interval; every returned ID and text value is checked.
The 5M-row table is not a claim that all 5M rows are touched. The actual finite
pool's decoded block working set is what determines residency.

Six arms run in six balanced Williams rounds, three seconds per arm, at each
of 20k/100k/500k/1M/5M rows. Only one arm is queried at a time; server creation
order rotates by size. Both 16 and 512 MiB configurations use **16 shards**.
The source/binary change and the capacity change therefore have separate
comparisons:

| Label | Binary | Entry ceiling | Adaptive flag | Purpose |
| --- | --- | --- | --- | --- |
| reference16 | Original #5042 `376fbf9` | 16 MiB | Absent | Default-mode source comparison |
| manual16 | Experimental | 16 MiB | 0 | Default-mode source comparison; capacity baseline |
| manual512 | Experimental | 512 MiB | 0 | Capacity candidate; policy baseline |
| adaptive512 | Same experimental binary | 512 MiB | 1 | Equal-ceiling policy effect |
| off0 | Same experimental binary | 0 | 0 | Cache-disabled baseline |
| off1 | Same experimental binary | 0 | 1 | Same effective disabled-cache path control |

Every group waits for a continuous 30-second gate with mean idle >=90% and
minimum interval idle >=80%. The first gate required several minutes;
thresholds were not relaxed. One-second CPU telemetry covers every timed
interval fully. Build, tests, sanitizer work and plot rendering were outside
timed collection. No CPU affinity/frequency controls or confidence intervals
are claimed.

Rates below are medians of six arm samples. Changes are ratios of those
medians; plotted and tabulated paired ranges are min/max of six within-round
ratios, not confidence intervals. No control subtraction is used. The adaptive
phase adds **180 primary timed arm samples / 2,481,672 checked timed queries**,
plus **12 diagnostic stage samples / 401,428 checked queries**. All samples,
including seven load-flagged primary samples, remain in the results.

## Throughput and capacity sweet spot

![Capacity versus sampled dataset size](figures/adaptive-cache-capacity.png)
''')
labels=['reference16','manual16','manual512','adaptive512','off0','off1']
table(['Rows','Original 16 MiB QPS','New manual 16 MiB','Manual 512 MiB','Adaptive 512 MiB','Cache off, flag 0','Cache off, flag 1'],[[f"{c['rows']:,}"]+[f(c['arms'][n]['qps_median']) for n in labels] for c in d['cases']])
table(['Rows','Manual 16→512 MiB QPS','CPU/query','Off→manual 512 MiB QPS','CPU/query'],[[f"{c['rows']:,}"]+[pct(c['comparisons'][name][metric]) for name in ['capacity16_to512','off_to_manual512'] for metric in ['qps_change_percent','cpu_query_change_percent']] for c in d['cases']])
add('''At 20k/100k the smaller ceiling already contains the touched blocks; increasing
it has no established throughput benefit. At 500k/1M a 16 MiB cache churns
while the 512 MiB ceiling can retain the pool's working set. The relative
capacity gain peaks at 500k among the sampled sizes and is smaller at 5M.
These sampled points do not locate a universal optimum or justify choosing
cache size from total row count alone. Projection width, decoded block reuse,
concurrency and memory headroom also matter.

The 5M pool retains about 408 MiB, rather than filling the ceiling. This
supports an explicit larger ceiling for this workload; it does not demonstrate
that every workload needs 512 MiB or that a 512 MiB cache bounds process RSS.

## Equal-ceiling policy and default-mode comparisons

![Policy, default-mode and disabled-cache controls](figures/adaptive-cache-policy.png)
''')
table(['Rows','Adaptive vs manual 512 QPS','CPU/query','Paired QPS min…max','Original→new manual 16 QPS','CPU/query','Cache-off flag 0→1 QPS','CPU/query'],[[f"{c['rows']:,}",pct(c['comparisons']['adaptive512']['qps_change_percent']),pct(c['comparisons']['adaptive512']['cpu_query_change_percent']),f"{pct(min(c['comparisons']['adaptive512']['paired_qps_changes_percent']))} … {pct(max(c['comparisons']['adaptive512']['paired_qps_changes_percent']))}",*[pct(c['comparisons'][name][metric]) for name in ['manual16_regression','cache_off_control'] for metric in ['qps_change_percent','cpu_query_change_percent']]] for c in d['cases']])
add('''The medians show small changes in both directions, while individual rounds
vary more. In particular, the 20k adaptive round-0 sample is load-flagged and
the paired policy range reaches -24.74%. It remains included. These data do
not prove zero overhead or a universal positive result. The disabled-cache
flag comparison executes the same effective cache-disabled path; it is a
control observation, not an adjustment or a formal noise band. This new phase
has no separate count-query control.

Server CPU is measured for the server process, divided by completed checked
queries; lower CPU/query is better. Client CPU and latency remain in raw JSON.
The absolute CPU/query medians are:
''')
table(['Rows']+[n+' CPU ms/query' for n in labels],[[f"{c['rows']:,}"]+[f"{c['arms'][n]['server_cpu_ms_per_query_median']:.4f}" for n in labels] for c in d['cases']])
add('''## Occupancy and process memory

Primary-sample medians, MiB. Charged cache entry bytes exclude hash tables and
allocator overhead. RSS includes additional process memory. The original
binary lacks the new cache-used metric; its RSS is still recorded in raw JSON.
''')
table(['Rows','Manual 16 cache / RSS','Manual 512 cache / RSS','Adaptive 512 cache / RSS','Cache off RSS'],[[f"{c['rows']:,}"]+[f"{c['arms'][n]['cache_used_bytes_median']/2**20:.3f} / {c['arms'][n]['rss_bytes_median']/2**20:.2f}" for n in ['manual16','manual512','adaptive512']]+[f"{c['arms']['off0']['rss_bytes_median']/2**20:.2f}"] for c in d['cases']])
add('''The separate transition diagnostic uses one 5M-row table. Each fresh server
queries the full 5M ID range, then a 20k hot prefix, then the 5M range again.
Each stage warms its query pool and runs for eight timed seconds. Two passes
reverse manual/adaptive order. Cache-used and RSS probes run every 0.2 seconds,
so these are memory diagnostics rather than primary throughput comparisons.
The figure normalizes phase widths; raw timestamps remain in JSON.

![Cached-entry reclamation and unchanged RSS](figures/adaptive-cache-working-set.png)
''')
table(['Pass','Mode','Large: cache / RSS MiB','Hot: cache / RSS MiB','Large again: cache / RSS MiB'],[[t['pass_number'],t['arm']]+[f"{p['used_bytes_after']/2**20:.2f} / {p['sample']['rss_bytes']/2**20:.2f}" for p in t['phases']] for t in d['transitions']])
add('''Both passes reproduce **407.92→15.93→408.86 MiB** of adaptive cached entries.
Manual mode retains **407.92→408.86→408.86 MiB**. However, adaptive RSS stays
roughly 632–635 MiB and does not fall when entries are freed. The experiment
therefore demonstrates entry reclamation and refill, **not lower process RSS
or memory returned to the operating system**. All diagnostic stage intervals
have full telemetry coverage and none meets the external-load flag.

Cold-entry deletion uses the existing payload `delete[]` and node deletion
paths. Allocator retention/fragmentation is a plausible explanation for the
RSS behavior; these measurements do not isolate its internals. This Apple
build has `HAVE_MALLOC_TRIM=0`; the existing `PerformMallocTrim` implementation
is a no-op here. No platform-specific allocator purge was added or invoked.
Linux/glibc or another allocator might behave differently and has not been
measured for this prototype. Released storage may be reusable inside the
process, but this experiment does not quantify that benefit under another
allocation workload or memory pressure.

## Load annotations and uncertainty

The monitoring flag is sample-average external CPU >10% of the machine or
any overlapping interval >20%. External CPU estimates surviving processes
outside benchmark process trees; short-lived external processes can be missed.
These flags are annotations, not exclusion criteria or proof of causation.
The seven flagged primary samples are:
''')
flags=[]
for c in d['cases']:
 for name,a in c['arms'].items():
  for x in a['sample_load']:
   if x['elevated_external_load']:flags.append([f"{c['rows']:,}",name,x['round'],f"{x['external_cpu_percent_machine_mean']:.2f}%",f"{x['external_cpu_percent_machine_peak']:.2f}%"])
table(['Rows','Arm','Round (zero-based)','Mean external CPU','Peak interval external CPU'],flags)
add('''All initial gates pass and all timed telemetry coverage is 100%, but a gate
cannot prevent later desktop activity. No claim is made that the machine was
isolated, all differences are caused by the code, or median changes around
1% are statistically significant. The earlier workstation-load and negative
results are retained in their original reports; they are not superseded by
selecting only favorable cells from this run.

## Implementation and validation boundaries

The measured production binary SHA256 is
`51c674f1ddbb1b676932bb9846708f55536063cd347deeadfa2605f38f3ce4a2`.
All six affected translation units were rebuilt using the recorded Clang 21
commands. A copy of the engine archive received the changed objects;
unchanged engine/dependency objects were reused. Exact commands, source
snapshots, patches and hashes are archived. This was not a fresh dependency
rebuild or whole-engine sanitizer build.

The generic LRU node adds a 32-bit access epoch and alignment padding even
when adaptive mode is off. Thus opt-in configuration does not make the default
binary layout identical to the old source. The original→new manual-16 arm
comparison measures the default SQL path; **SkipCache performance was not
benchmarked**, although its affected translation unit was rebuilt and focused
sanitizer coverage includes it. This is a reason to keep the change experimental
until the generic metadata cost and allocator behavior are assessed further.

Final tests strengthen the public stored-field concurrent case to exercise
real cold-block reclamation: about 24 MiB of decoded fields, a 32 MiB entry
ceiling, eight readers, followed by a smaller hot range. Every returned field
is checked and retained bytes must shrink. Other tests cover same-key
replacement, clear/recreate, tiny-budget fallback, pinned references, hard
limits, growth and concurrent admission/reclamation.

- Full native suite: **529/529 passed** on final test source.
- Focused native tests: **11 tests ×20 passed**.
- ASan+UBSan: **11 tests ×20 passed**, fail-fast alignment/UB checks.
- TSan: **11 tests ×20 passed**, including real stored-field reclamation.
- API smoke: passed with the additional status metric golden. Initial fixture
  setup failure is retained separately.
- Every timed SQL response and post-timing REPLACE/flush/DROP/recreate
  lifecycle check passed. Native DocID used bytes were checked as zero.
- The driver scheduling/query-pool and telemetry-weighting selfchecks passed;
  the summarizer verifies exact driver/source hashes, medians, ratio formulas,
  paired ranges, ceiling bounds, lifecycle checks and complete timed coverage.

Sanitizers instrument docstore, SkipCache, file I/O and focused tests; other
linked libraries are reused uninstrumented. LeakSanitizer is unsupported on
this macOS runtime: the failed startup log remains and passing ASan runs use
`detect_leaks=0`. No leak-detection claim is made. Supported stack-calibration
overrides are inherited from the earlier Clang 21 build; no fresh automatic
calibration was attempted.

One strengthened-test ASan repeat failed a **test assertion**, with 17,280
retained bytes versus an asserted 16,384-byte floor. Thread phases overlap;
the policy can stop shrinking when touched bytes reach a quarter of retained
bytes. The test incorrectly treated the floor as guaranteed final occupancy.
It now asserts contraction below 32 KiB for the four-entry hot set and still
checks all read values. The failed log remains under `asan-ubsan-final/`;
passing final reruns are under `*-validated/`. No production logic changed to
make the test pass.

Measured `candidate-source/`, `adaptive-cache.patch` and `build-manifest.json`
remain untouched. After timing, only the stronger test and two English
documents changed. `final-validation/manifest.json` proves that production
sources and the measured searchd binary are unchanged and records the final
source patch separately. Tests do not link into searchd. The experiment source
commit contains those final test/document changes.

#5042 CI fixes remain pushed at `376fbf9`; upstream
[run 43408089087](https://github.com/manticoresoftware/manticoresearch/actions/runs/43408089087)
is completed with conclusion **`action_required`**, with **zero jobs**, awaiting
maintainer fork-workflow approval. It is not a green CI result. That run does
not validate this separate experimental branch. No Windows/Linux production
throughput or prototype cross-platform CI success is claimed.

## Practical interpretation

A larger explicit ceiling is already useful when reused decoded blocks outgrow
16 MiB. The tested manual `512m` mode provides the observed capacity benefits
without requiring a new adaptive setting. The prototype adds cold-entry
reclamation, with no demonstrated steady-state throughput advantage or RSS
saving on this machine. Keep it separate from the production PR until its
memory benefit is established for the intended allocator and workloads.

Reproduce using the [adaptive section of the guide](repro/2026-11-13/README.md#adaptive-cache-follow-up),
and keep capacity, policy, default-mode and reader-TLS comparisons separate.
''')
(p/'ADAPTIVE_CACHE_2026-11-13.md').write_text('\n'.join(parts))
print('Wrote English adaptive report with all six arms, CPU, memory and flags.')
