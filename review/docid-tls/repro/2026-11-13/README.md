# Reproduction for the 2026-11-13 review

These standard-library Python drivers use loopback daemons and disposable RT
fixtures. They check every returned row/text/count. Eight independent client
processes use persistent HTTP connections, eight server query workers and a
fixed 8 MiB reader-buffer budget. Query cache is disabled.

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
