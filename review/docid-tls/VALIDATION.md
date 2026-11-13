# Validation record

Updated review (2026-11-13): [#5042 shared-block-cache results and CI fixes,
without TLS](BLOCK_CACHE_2026-11-13.md); [#5045 default-cache/large-data,
lifetime and churn answers](TLS_REVIEW_2026-11-13.md). The sections below retain
the dated original evidence; their patches/test counts are historical, not the
current expanded #5042 validation. New and old measurements are separate.


## Current #5042 validation (2026-11-13)

| Check | Result |
| --- | --- |
| Both final no-TLS arms, full GoogleTest | 521/521 each |
| API smoke | Passed on each rebuilt arm |
| Candidate DocID SQL lifecycle | Passed at 0/1 KiB/16 MiB |
| Focused ASan+UBSan / TSan | Each 26 tests ×20, fail-fast alignment enabled |
| Upstream CI after push | action_required, zero test jobs, maintainer approval needed |

The fixes, pre-fix failures, exact sanitizer scope, local Apple calibration
workaround, source/binary hashes and CI state are documented in the
[current report](BLOCK_CACHE_2026-11-13.md). The #5045 supplemental reader
review separately passed 499/499 tests per arm and eight focused reader tests
×20 per sanitizer; production source remains unchanged. These are distinct
source trees/test counts, not one combined validation claim.

## Reader TLS on the latest block-cache context (2026-11-13)

The latest [two-dataset TLS report](TLS_REVIEW_2026-11-13.md) builds reference
`376fbf9` and the same source plus only #5045's reader production diff. Both
use the shared XXH3/sharded block cache, disabled native DocID cache, identical
CI/alignment repairs and eight supplemental reader tests. Both full suites
passed **529/529**. Focused ASan+UBSan and TSan each passed **11 tests ×20**
(eight reader plus three block-cache cases), instrumenting docstore, file I/O
and tests while reusing other engine archives. Alignment remains fail-fast.

The current build uses identical inherited supported stack-calibration exports
in both arms; no fresh automatic calibration was attempted. These are a local
Apple workaround, not a production change or a newly calibrated-stack claim.
Source snapshots, exact TLS-only patch, flags, test logs and binary hashes are
under `evidence/2026-11-13/tls-latest-block/`. The original-cache 499-test results
remain separately identified. #5045 source still contains only its TLS patch;
the latest block-cache code is benchmark context, not a PR dependency.

The load-recorded reruns reuse these exact validated binaries; no recompilation
or production edit occurred between phases. The driver checks every timed
response and repeats the same post-timing REPLACE/flush and DROP/recreate
lifecycle checks. The new harness selfchecks cover telemetry CPU parsing,
benchmark-descendant exclusion and query-pool shape; per-case load records
and startup/binary/script hashes are archived with the timing data.

## Original snapshot

Prepared locally on 2026-10-27. Upstream base:
`047d2f99522d78e0aa1de7e7dc945a9abe1b673a`; pinned MCL:
`88b5412a243ab0439957203acfe86c09944280d3`.

Validation was completed before publication in an isolated worktree at the
stated upstream base, with MCL sources at the pinned commit. Temporary benchmark
daemons used loopback ports and synthetic data. The original experiment
worktree was preserved.

## Patch structure

`repro/verify_patches.py` checked each patch independently, then both application
orders, using temporary Git indexes. `git apply --check` and whitespace checks
passed. The two combined trees are identical. Exact trees, patch hashes and
file statistics are in `evidence/patch-application.json` and `patch-layout.json`.

Patch 1 contains 18 files and excludes the docstore TLS code/tests. Patch 2
contains three files and has no dependency on the new DocID module or setting.
The production patch omits the local Google Benchmark SSL-link workaround,
POSIX-only point-benchmark helper, historical reports and this review package.
Core C++ tests use the existing upstream GoogleTest target; the standard-library
SQL lifecycle helper is documented for explicit invocation.

## Fresh builds against the upstream base

Apple M4 Pro, arm64, Apple Clang 21, RelWithDebInfo `-O2`.
Configuration: BUILD_TESTING=ON, MCL_LOCAL_RUNTIME=OFF, dynamic ICU ON;
Galera, MySQL/PostgreSQL/ODBC sources, Jieba, RE2 and Snowball disabled.
Full configuration/build logs are in `evidence/upstream-main/`.

| Source state | Check | Result |
| --- | --- | --- |
| Upstream implementation + five new reader tests, before TLS | Reader API/lifecycle tests | 5/5 passed |
| Upstream + TLS only | Build searchd/gmanticoretest and full GoogleTest suite | 496/496 passed |
| Upstream + DocID only | Build searchd/gmanticoretest and full GoogleTest suite | 517/517 passed |
| Upstream + DocID only | SQL lifecycle at 0 / 1 KiB / 16 MiB budgets | All passed |
| Upstream + both patches, first direct run | Full suite | 521/522; JSON death-test child SIGBUS (retained) |
| Upstream + both patches, own build calibration inherited | Full suite | 522/522 passed |
| Upstream + both patches | SQL lifecycle at 0 / 1 KiB / 16 MiB budgets | All passed |

The TLS-before binary contains upstream production code; adding test
registration does not link tests into searchd. The after binary changes only
the TLS production implementation. Both copies were saved before other patches
were applied. The independent SQL matrix uses no DocID prototype setting.
All stored-field queries, count controls and post-run replacement/drop-recreate
checks passed in the main four-round matrix and focused six-round repeat.

Both benchmark arms inherit the same supported MANTICORE_* stack-calibration
exports from this fresh build's successful TLS GoogleTest log. This records
a local Apple toolchain workaround; the values are not portable defaults.
The independent TLS and DocID full GoogleTest runs were launched directly.
The first combined run passed 521/522: `JsonFileParseTest.InterruptedRead`
reported a child terminated by signal 10 (SIGBUS). This matches an earlier
pre-TLS Apple experiment symptom; its root cause remains undiagnosed. The
original failure log is retained. The combined rerun uses the combined build's
own exported calibration values, and is reported separately below.

## Focused sanitizer evidence from the earlier experiment tree

The code modules match the prepared patch sources; the original experiment
base was `5e8fc00f55efeee8dba760f13f5ccb09ea7b2382`. Exact source hashes and logs
are retained rather than relabeling these as new full-engine sanitizer runs.

- Core cache: 14/14 ASan+UBSan tests on actual Apple/128 B, forced 64 B,
  forced 256 B, and actual N100/Linux/64 B hardware.
- Four concurrent/consecutive cache cases passed Apple TSan.
- Five public docstore reader tests passed 20 ASan+UBSan repetitions and
  20 TSan repetitions. Those builds instrumented docstore.cpp, fileio.cpp and
  the new tests while reusing unchanged engine dependencies.
- Full original combined experiment suite passed 522/522; fresh independent
  builds above prevent that combined result being mistaken for TLS-only scope.

The new compact layout reproduction driver compiled both archived source pairs
successfully with warnings treated as errors. Python reproduction tools pass
`py_compile`. The source pairs match the current adaptive module and recorded
fixed-16 comparison. The prior N100 experiment's isolated container/tree cleanup
is recorded in its archived log; no N100 service was modified in this preparation.

## Practical limits before upstream acceptance

Full UberTest/CLT, Windows, Linux full-engine/SQL, full-engine sanitizer coverage,
long mixed read/write endurance and production traffic are not established by
these local runs. No process-RSS saving or universal QPS gain is claimed.
The complete negative/control samples are retained in PERFORMANCE.md and raw JSON.

CONTRIBUTING.md recommends discussing changes with maintainers and rebasing on
current main; the package is prepared at the stated main SHA. Upstream cross-platform
CI results are reported on the PRs; this record describes the local validation
completed before publication.
