# Reproduction for the 2026-11-13 review

These standard-library Python drivers use loopback daemons and disposable RT
fixtures. They check every returned row/text/count. Eight independent client
processes use persistent HTTP connections, eight server query workers and a
fixed 8 MiB reader-buffer budget. Query cache is disabled.

## #5045: both original-cache and latest-cache datasets

The current [TLS report](../../TLS_REVIEW_2026-11-13.md) retains two datasets.
For the latest pair, use `376fbf9` as the production baseline and apply only
`git diff 047d2f9 019868e9 -- src/docstore.cpp` for the TLS candidate. Both arms
therefore use #5042's shared sharded-LRU/XXH3 block cache, common alignment/CI
repairs and native DocID code disabled at budget zero. The eight supplemental
reader tests and CMake registration are identical in both builds. The exact
production patch, complete source snapshots, flags, binary hashes and build
commands are under `../../evidence/2026-11-13/tls-latest-block/`.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tls_latest_block.py --selfcheck
PYTHONDONTWRITEBYTECODE=1 python3 tls_latest_block.py \
  LATEST_CACHE_NO_TLS_SEARCHD LATEST_CACHE_WITH_TLS_SEARCHD \
  --fixtures /tmp/fixtures --output /tmp/tls-latest.json --rounds 6 --duration 3
PYTHONDONTWRITEBYTECODE=1 python3 tls_latest_block.py \
  LATEST_CACHE_NO_TLS_SEARCHD LATEST_CACHE_WITH_TLS_SEARCHD \
  --fixtures /tmp/fixtures --output /tmp/tls-latest-repeat.json \
  --rounds 6 --duration 5 --order-offset 0 \
  --cases rows20000-cache16777216 rows1000000-cache16777216 rows5000000-cache16777216
```

Run `mixed-1000000` separately with the same repeat options. A five-second
`aa-1000000` run with `--order-offset 1` was added after the 1M sign reversal;
`additional-aa-plan.json` records that reason, and its samples are a separate
phase. The archived
measurement plan selected these repeats before initial results. Their starting
orders reverse the corresponding initial cases. The matrix has 16 size/budget
text cells plus two count, two point, one A/A and one mixed control. DocID used
bytes must be zero before each post-timing lifecycle check. A/A uses the no-TLS
binary twice. The original-cache matrix remains reproducible with
`scale_benchmark.py` and upstream `047d2f9` / TLS `019868e9` binaries; it uses
no DocID setting because that module is absent in those sources.

The original and latest phases use the same fixture snapshots and text-query
pools, with their SHA256s checked in the report. Their source contexts and
measurement times differ. Compare TLS off/on ratios within each pair; do not
attribute differences between separate absolute rates to TLS or multiply gains.
Build and sanitizer runs must finish before starting either timed matrix.

The latest build reuses supported MANTICORE_* overrides from an earlier
upstream/Clang 21 build, equally in both arms; no new auto calibration was
attempted. Both arms passed 529 tests with these overrides. Focused reader/block
sanitizers use `sanitize_readers.py --with-block-cache` and passed 11 tests ×20
for each of ASan+UBSan and TSan, with fail-fast alignment checks. Other libraries
are reused and this is not whole-engine sanitizer coverage.

After timing, render the English comparison figure (matplotlib required):

```sh
python3 plot_tls_cache_comparison.py --evidence ../../evidence/2026-11-13 \
  --output ../../figures
```

The historical original-cache chart remains available in its historical report.
The current PR description uses the paired original/latest figure and tables.

## #5042: no reader TLS

The production candidate is commit `376fbf9988b2458ee196a5d92135c35a5121edc7`.
The comparison baseline is `1514b3e` (same DocID implementation, CI and alignment
repairs, before shared-block-cache sharding/XXH3). Build each with identical
configuration and save each `searchd` outside its build directory. Exact native
configure/build commands and source/binary hashes are under
`../../evidence/2026-11-13/block-cache/`. Tests are not linked into searchd.
Neither arm contains the #5045 reader TLS or its global generation counter.
The original 18-file DocID patch plus `../../patches/03-docid-ci-and-block-cache.patch`
reproduces the expanded candidate; the old patch remains a historical snapshot.

Build dependencies follow upstream TESTING.md. The recorded Apple build uses
Clang 21 `-O2 -DNDEBUG`, MCL `88b5412`, BUILD_TESTING=ON, MCL_LOCAL_RUNTIME=OFF,
dynamic ICU, and disables Galera, MySQL/PostgreSQL/ODBC sources, Jieba, RE2 and
Snowball. Configuration and compile commands are archived. No benchmark is run
while compiling, testing, sanitizing or collecting diagnostic counters.

Prepare fixtures of 16/256/1024/4096/20k/100k/500k/1M/5M rows with the same
128-byte generator used by `scale_benchmark.py`. Existing fixture snapshots are
cloned for each arm and checked by the driver. For a new fixture directory:

```sh
python3 - <<'PYFIX'
from pathlib import Path
from benchmark import make_fixture
Path('/tmp/fixtures').mkdir(parents=True, exist_ok=True)
for n in (16, 256, 1024, 4096, 20000, 100000, 500000, 1000000, 5000000):
    make_fixture('/path/to/candidate/searchd', Path('/tmp/fixtures') / f'fixture-{n}', n)
PYFIX
python3 compare_blockcache.py --selfcheck
python3 cache_toggle.py --selfcheck
python3 compare_blockcache.py BEFORE_SEARCHD CANDIDATE_SEARCHD \
  --fixtures /tmp/fixtures --output /tmp/docid0.json --docid-cache 0 \
  --rounds 6 --duration 3
python3 compare_blockcache.py BEFORE_SEARCHD CANDIDATE_SEARCHD \
  --fixtures /tmp/fixtures --output /tmp/docid128m.json --docid-cache 134217728 \
  --rounds 6 --duration 3 --cases small-default 1m-default 5m-default
python3 cache_toggle.py CANDIDATE_SEARCHD --fixtures /tmp/fixtures \
  --output /tmp/cache-toggle.json --docid-cache 0 --rounds 6 --duration 3 \
  --cases rows16-c8-point rows256-c8-b64 rows20000-c8-b256
```

Repeat the toggle with `--docid-cache 134217728`. Use `--order-offset 1` and
`--duration 5` for a reversed-order longer repeat. The published reports list
exact subsets and every completed phase separately. The disabled DocID-cache
budget is the default, distinct from the default 16 MiB docstore block cache.
The enabled 128 MiB DocID budget fits even all tested 5M-row chunks; actual
admitted bytes are checked/recorded before lifecycle mutation in both arms.

Raw arm name `tls` is inherited from the original measurement helper: in
`compare_blockcache.py` it means the block-cache **candidate without TLS**;
in `cache_toggle.py` it means **16 MiB cache on in the same binary**. Output
metadata and binary hashes identify those meanings. A/A uses the baseline
binary twice. Comparison ratios and on/off ratios answer different questions.

The local Apple auto stack calibration failed before tests. Both arms passed
521 tests with identical supported `MANTICORE_*` overrides inherited from an
earlier upstream/Clang 21 build. The failure note and values are archived. They
are a local test workaround, not a production change or portable recommendation;
calibrate for your build. `../../repro/run_with_calibration.py` can extract exports
from a successful build log. Do not silently use the archived numbers elsewhere.

## Focused sanitizers

A native Unix Makefiles build must already contain the registered cache tests:

```sh
python3 sanitize_caches.py SOURCE BUILD --output /tmp/cache-asan \
  --sanitizer address,undefined --repeat 20
python3 sanitize_caches.py SOURCE BUILD --output /tmp/cache-tsan \
  --sanitizer thread --repeat 20
```

This recompiles docstore/fileio/DocID-cache/lookup sources and three test files,
then links unchanged remaining engine archives. It runs 26 tests ×20 with
fail-fast sanitizer handling and alignment checks enabled. This is focused,
not whole-engine, coverage. ASan+UBSan and TSan must be separate. Both final
runs passed; the earlier failing alignment logs are retained. The native full
suite/API smoke and standalone `test/docid-cache/test_integration.py` are separate.

## Added 0 / 8 / 16 MiB matrices, with and without reader TLS

Use `block_cache_budgets.py` with the no-TLS `1514b3e` / `376fbf9` binaries
identified by the existing build manifest. Use `tls_block_cache_budgets.py` with
the latest-context `376fbf9` / same-plus-reader-diff binaries. Each driver fixes
native DocID budget 0 and query cache off; the separate reader buffers stay at
8 MiB. Fixture snapshots are the same `fixture-N` directories as the size sweep.

Apply the exact supported calibration exports in the corresponding archived
`calibration.json` to both arms, using the recorded commands; these local
Apple workaround values are not portable defaults. Use macOS for the supplied
host telemetry. Keep this task's builds, tests and plot rendering outside timing.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 block_cache_budgets.py OLD_CACHE_SEARCHD NEW_CACHE_SEARCHD \
  --fixtures /tmp/tls-fixtures --output /tmp/no-tls-budgets/matrix.json --controls
PYTHONDONTWRITEBYTECODE=1 python3 block_cache_budgets.py OLD_CACHE_SEARCHD NEW_CACHE_SEARCHD \
  --fixtures /tmp/tls-fixtures --output /tmp/no-tls-budgets/repeat.json \
  --rows 20000 5000000 --duration 5 --reverse
PYTHONDONTWRITEBYTECODE=1 python3 tls_block_cache_budgets.py LATEST_NO_TLS_SEARCHD LATEST_TLS_SEARCHD \
  --fixtures /tmp/tls-fixtures --output /tmp/tls-budgets/matrix.json --controls
```

Create the output directories first. Six live arms are queried one at a time,
using six balanced Williams rounds x three seconds/arm by default. A 30-second
pre-group idle gate requires mean >=90%, minimum >=80%; one-second CPU logging
and thermal/swap/VM snapshots cover warmup and timing. No sample is rejected by
its load flag. The new logger waits for a point beyond the final timed interval.
Both no-TLS endpoint repeats were selected before outcomes. A/A uses candidate
8 MiB in both labeled arms: no TLS in the first matrix, TLS on in the combined
matrix. Every timed response and post-timing lifecycle check is validated.

The archived no-TLS `driver/` is the exact pre-wrapper version; the TLS driver
and public default differ only by optional TLS comparison metadata. Preserve
both snapshots when checking recorded script hashes. For a new collection,
archive its exact helpers beside the JSON as `driver/` before summarizing.
The checked-in collection can be summarized and plotted with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 block_cache_budgets.py --selfcheck
python3 summarize_cache_budgets.py --selfcheck
python3 summarize_cache_budgets.py --evidence ../../evidence/2026-11-13 \
  --output ../../evidence/2026-11-13/cache-budgets-summary
python3 plot_cache_budgets.py \
  --summary ../../evidence/2026-11-13/cache-budgets-summary/summary.json --output ../../figures
```

Plotting uses the same Matplotlib environment as the other review charts.
Summary validation checks all medians/ratios, per-run helper hashes, common
query pools/fixture metadata, disabled DocID usage, successful lifecycle checks
and full timed-interval load coverage. The [budget report](../../BLOCK_CACHE_BUDGETS_2026-11-13.md)
separates all three denominators and gives the raw-data/ZIP links. The previous
521/529-test and sanitizer evidence remains separately scoped; binaries were
reused without a fresh full-suite or automatic-calibration claim.

## #5045: latest shared block-cache context and load-recorded reruns

The latest reference is `376fbf9988b2458ee196a5d92135c35a5121edc7` (#5042).
The candidate has the same source plus **only** the production diff below:

```sh
git diff 047d2f99522d78e0aa1de7e7dc945a9abe1b673a \
  019868e9f79d1bb2bd1f96dafb88ef20acd45418 -- src/docstore.cpp > reader-tls-only.patch
```

Build both with identical flags/dependencies and the same supplemental reader
tests. Their full suites contain 529 tests each. Both use the latest shared
shards/XXH3; DocID budget and SQL query-result cache are explicitly zero. No
block-cache production diff is added to #5045. Use the original fixture snapshots
(or rebuild with the generator above), then:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tls_latest_block.py --selfcheck
PYTHONDONTWRITEBYTECODE=1 python3 tls_latest_block.py BEFORE_SEARCHD TLS_SEARCHD \
  --fixtures /tmp/tls-fixtures --output /tmp/latest-matrix.json --rounds 6 --duration 3
PYTHONDONTWRITEBYTECODE=1 python3 load_telemetry.py
PYTHONDONTWRITEBYTECODE=1 python3 tls_load_controlled.py --selfcheck
PYTHONDONTWRITEBYTECODE=1 python3 tls_load_controlled.py BEFORE_SEARCHD TLS_SEARCHD \
  --fixtures /tmp/tls-fixtures --output /tmp/load-controlled-1.json \
  --rounds 6 --duration 5 --order-offset 0 --cases \
  rows20000-cache0 rows20000-cache16777216 rows100000-cache16777216 \
  rows500000-cache16777216 rows1000000-cache16777216 rows5000000-cache16777216 \
  count-1000000 aa-1000000
```

For pass 2, use a new output filename, `--order-offset 1` and `--reverse-cases`.
The macOS telemetry driver requires 60 seconds of mean >=90% and minimum >=80%
system CPU idle before every case, with a 15-minute timeout. It logs one-second
CPU deltas for external processes, excluding the benchmark process tree, and
host CPU/load. Thermal/swap/VM snapshots bracket each case. These checks do not
stop external applications or reject completed samples. External processes
that exit within an interval can be missed. The published summary labels
higher external load and retains all samples; the logs are not a formal
attribution of performance differences.

Normal `--nodetach` startup is retained; CPU placement/frequency and exclusive
machine access are uncontrolled. The original driver/plan's exploratory UID
note is superseded by the source-order audit: preloading precedes `SetUidShort`,
so no startup-dependent shard-routing variability is established for these
fixtures. Runtime index IDs were not instrumented.
The [TLS report](../../TLS_REVIEW_2026-11-13.md) keeps the original,
latest initial, earlier repeats and both load-recorded passes separate. The
archived `driver/`, `load-controlled-driver/` and `load-controlled-reversed-driver/` directories preserve the exact
helper versions used in those phases, with per-run hashes. Supported stack
exports are inherited identically from the recorded build; calibrate your own
build rather than treating those recorded values as portable defaults.

After timing is complete, render both figures with matplotlib:

```sh
python3 plot_tls_cache_comparison.py --evidence ../../evidence/2026-11-13 \
  --output ../../figures
python3 plot_tls_load_controlled.py --evidence ../../evidence/2026-11-13 \
  --output ../../figures
```

## #5045: TLS-only historical follow-up

Use upstream `047d2f9` versus `019868e9`, same build/dependencies, without #5042.
The additional reader tests are `gtests_docstore_readers.cpp` and
`../../patches/reader-supplemental-tests.patch`. Their full test counts are
499/499 for each arm, not #5042's 521. Scripts `benchmark.py`,
`scale_benchmark.py`, `diagnose.py`, `scale_diagnose.py`, `build_diagnostic.py`
and `profile_cache.py` support the historical experiment. To reproduce:

```sh
python3 benchmark.py BEFORE_SEARCHD TLS_SEARCHD --work /tmp/tls-fixtures \
  --output /tmp/tls-matrix.json --rounds 6 --duration 3
python3 scale_benchmark.py BEFORE_SEARCHD TLS_SEARCHD --work /tmp/tls-fixtures \
  --output /tmp/tls-scale.json --rounds 6 --duration 3
python3 sanitize_readers.py SOURCE BUILD --output /tmp/tls-asan \
  --sanitizer address,undefined --repeat 20
```

The scale driver keeps eight clients, 256 returned rows, seed 513 and 20 query
templates/client fixed while varying dataset/cache size. The broader driver
has different query pools. Do not mix those phases. Diagnostic counters include
warmup/plan probes and are collected separately; never time instrumented binaries.

`hash_keys.py` and `hash_compare.cpp` reproduce the independent scalar hash
experiment on actual block offsets. XXH3 uses the offset with index ID as seed;
CRC/BKDR process all binary key bytes, including zeros. The historical archive
preserves the input keys and compiler command. Hash ns/key is not SQL QPS.
`block-cache-*.patch` are the original follow-up prototype patches based on
TLS; current #5042 reproduction uses the incremental patch above instead.

Reports: [shared block cache](../../BLOCK_CACHE_2026-11-13.md),
[TLS review](../../TLS_REVIEW_2026-11-13.md). Full historical prototype phases,
including both arms having TLS, are separately retained in the historical ZIP.
They are never treated as measurements of the final #5042 candidate.

## Figures

Install matplotlib in an isolated environment, then render PNG/SVG files from
the published raw evidence (never render plots during timed comparisons):

```sh
python3 plot_results.py --evidence ../../evidence/2026-11-13 \
  --output ../../figures
```

The size figure includes a supplemental 500K-row run. Its source-driver snapshot
and the initial phase's snapshot are both archived because the case was added
after the initial matrix. Vertical ranges show the six paired-round changes,
not confidence intervals. Connecting lines guide the eye; the plots do not
infer unmeasured optima. The 5M budget chart shows both QPS and RSS.


## Adaptive cache follow-up

The [experimental report](../../ADAPTIVE_CACHE_2026-11-13.md) is separate from
both production PRs. Build original #5042 `376fbf9` and experimental source
`ad885be366eda4e897c828f05cb93ff04702d02c` with equal build configuration.
The experiment adds `docstore_cache_adaptive`, default 0, and a status metric.
Its manual512/adaptive512 arms run the same binary at an equal 512 MiB entry
ceiling. There is no reader TLS. Existing defaults remain unchanged.

The recorded build recompiled all six affected translation units and replaced
changed archive objects; unchanged engine/dependency objects were reused.
`../../evidence/2026-11-13/adaptive-cache/` includes exact native/sanitizer
commands, the measured driver snapshot, source/binary hashes, calibration
exports, raw timing/CPU/RSS data and the plan saved before results. Final
validation strengthened only tests and English docs; the timed production
sources/searchd hash remained unchanged. Use `final-validation/` for the
final source/test snapshot and `candidate-source/` for the timed-build snapshot.
Absolute local paths in archived commands describe this machine; rebuild with
normal upstream CMake/dependency setup in another checkout rather than running
those commands against an unrelated build directory.

Using fixtures prepared with the earlier guide:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 adaptive_cache.py --selfcheck
PYTHONDONTWRITEBYTECODE=1 python3 adaptive_cache.py \
  ORIGINAL_376FBF9_SEARCHD EXPERIMENTAL_AD885BE_SEARCHD \
  --fixtures /tmp/fixtures --output /tmp/adaptive/sql
```

Six arms cover original manual16, new manual16, new manual512, adaptive512,
and cache off with the adaptive flag 0/1. Five sizes, six balanced Williams
rounds, three seconds per arm, full idle gates and CPU telemetry. Each client
warms its 20-query pool before timing. Both 16 and 512 MiB use 16 shards.
The two memory passes use fresh servers, reverse arm order and query a broad
range, then a small hot range, then broad again on the same 5M table, with
concurrent 0.2-second status/RSS probes. Do not treat diagnostic QPS as the
primary throughput comparison.

To regenerate the published summary/figures from archived evidence:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 summarize_adaptive_cache.py \
  ../../evidence/2026-11-13/adaptive-cache
python3 plot_adaptive_cache.py ../../evidence/2026-11-13/adaptive-cache \
  --output ../../figures
```

The summarizer checks driver/source hashes, all median/ratio/paired-range
formulas, ceilings, lifecycle checks, idle gates and full telemetry overlap.
It retains all flagged samples. The plots separate the capacity comparison
from equal-ceiling adaptive policy and graph both entry occupancy and RSS.
Released entries do not prove RSS savings. The experiment's known gaps include
SkipCache throughput, a fully idle timer, Linux allocator/RSS behavior,
production-rate metric polling and adaptive-plus-TLS measurements.
