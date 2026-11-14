# REPLACE CI timing diagnosis — 2026-11-14

The failing upstream run was [43549129898, attempt 2](https://github.com/manticoresoftware/manticoresearch/actions/runs/43549129898/attempts/2). All SQL-result comparisons in the REPLACE CLT test passed. The columnar timing assertion failed: 8,898 ms for 5,000 `REPLACE ... SET` statements divided by 658 ms for 5,000 `REPLACE ... VALUES` statements yielded integer 13, exceeding the unchanged threshold of 12. Rowwise yielded integer 12 and passed. The later comment-permission error was secondary to this assertion.

A separate upstream run at `ef2bec585` passed with rowwise 11,426/1,032 ms (integer 11) and columnar 14,028/1,432 ms (integer 9). These were different runners/runs; their absolute times do not establish a causal PR speedup or regression.

## Controlled reproduction of the previously tested code

[Diagnostic run 43559647905](https://github.com/orca-zhang/manticoresearch/actions/runs/43559647905) ran the **unchanged complete CLT test four times**, in upstream → PR → PR → upstream order, on one Ubuntu 22.04 GitHub-hosted runner. Every replay started a fresh container and regenerated its rowwise and columnar million-row fixtures. No threshold, query, fixture-size or expected-output changes were made.

The PR image is the exact `manticore_test_kit.img` artifact from the failing run. The upstream arm substitutes only `/usr/bin/searchd` from `test-kit-ci-ef2bec58593d167ca67ee38107a10ee7c5c3da5e` into that PR image. Buddy, executor, runtime libraries, configuration and test infrastructure are therefore shared. This historical PR image has native DocID caching disabled by default; validation of the new default-on implementation is kept separate below. Version output confirms upstream `ef2bec585`, PR merge binary `0510070e1`, and MCL `b5ffd36` in both. CLT is pinned at `c558b2792d24590d7716564ba4ed3f1d3d1d00ff`.

All four complete tests exited zero, including SQL-result comparisons and the original timing assertions:

| Round | Binary | Engine | SET ms | VALUES ms | Integer ratio | Result |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | Upstream `ef2bec585` | rowwise | 10,472 | 1,052 | 9 | Pass |
| 1 | Upstream `ef2bec585` | columnar | 11,073 | 1,266 | 8 | Pass |
| 2 | Tested PR merge `0510070e1` | rowwise | 10,518 | 1,045 | 10 | Pass |
| 2 | Tested PR merge `0510070e1` | columnar | 11,443 | 1,285 | 8 | Pass |
| 3 | Tested PR merge `0510070e1` | rowwise | 10,318 | 1,027 | 10 | Pass |
| 3 | Tested PR merge `0510070e1` | columnar | 12,317 | 1,271 | 9 | Pass |
| 4 | Upstream `ef2bec585` | rowwise | 10,299 | 1,064 | 9 | Pass |
| 4 | Upstream `ef2bec585` | columnar | 11,858 | 1,256 | 9 | Pass |

The original ratio failure was not reproduced in these controlled runs. This is a small diagnostic sample, not a throughput benchmark or proof that timing failures cannot recur. In particular, a ratio of two different operations can move when either operation's time changes. The SET path includes Buddy work; the VALUES path is a native operation. The existing test also includes SQL-file generation inside both timing windows.

## Current runtime and integration-test fix

The current runtime, `a1dd0db409e2365cf372a13c18cdc1cb72a6b029`, built successfully on Linux with Clang 16.0.6 in RelWithDebInfo mode: [build job](https://github.com/orca-zhang/manticoresearch/actions/runs/43560597362/job/132343176014). MCL API headers come from the checked-out submodule; installed runtime modules are reused (`MCL_LOCAL_RUNTIME=0`), as in upstream's Linux test build.

Two more **unchanged full REPLACE CLT replays** passed using that binary with its new default-on native cache and the installed MCL runtime. The [CLT step](https://github.com/orca-zhang/manticoresearch/actions/runs/43562760053/job/132349870844) succeeded; that job's overall failure was the separate integration-test assumption described below.

| Replay | Engine | SET ms | VALUES ms | Integer ratio | Result |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | rowwise | 10,421 | 1,103 | 9 | Pass |
| 1 | columnar | 11,903 | 1,273 | 9 | Pass |
| 2 | rowwise | 10,100 | 1,038 | 9 | Pass |
| 2 | columnar | 11,031 | 1,322 | 8 | Pass |

The original `13 > 12` failure was therefore not reproduced in four historical-binary comparison replays or two current-runtime replays. The original CLT queries, million-row fixtures and integer-ratio threshold remain unchanged. These replays establish the observed pass/fail results; they do not establish a Linux throughput speedup or rule out future timing variation.

**The independent Linux checks exposed an integration-test portability problem.** With MCL installed, filtered `COUNT(*)` can be precomputed from a secondary index, bypassing lookup planning and cache construction. The old Python warmup consequently allocated zero native bytes and failed its cache-admission assertion. After changing warmup to return IDs, the next assertion exposed another valid behavior: the automatic planner chose `id:SecondaryIndex (100%)` rather than `DocidIndex`.

[Test-only follow-up `df13f6ce7`](https://github.com/orca-zhang/manticoresearch/commit/df13f6ce7d5b1ce40d21408b4ab33b97a32e3148) returns and checks all expected IDs during warmup and plan checks. It accepts either valid automatic indexed plan while still requiring cache allocation within the configured limit, exact results, and strict force/disable DocID-hint behavior. Cache-aware planner unit tests retain their specific lookup-selection assertions. Runtime sources are identical to `a1dd0db`; recorded performance measurements remain applicable to the same production sources.

[Final Linux validation](https://github.com/orca-zhang/manticoresearch/actions/runs/43563451039) passed:

- 63 focused native-cache, lookup, planner, block-cache, admission and memory-pool GoogleTests.
- Four complete native lifecycle runs: omitted default, disabled, refused 1 KiB, and admitted 16 MiB. Admitted runs allocate 122,367 native bytes; refused/disabled runs allocate zero.
- Six docstore switch/configuration cases, including stored-field replacement and cache cleanup.

The corrected native lifecycle script also passes all four budgets on Apple M4 Pro / Clang 21 with the existing runtime-equivalent binary. The Linux validation's tested Python blob is identical to the published test-only follow-up.

Upstream workflows for `df13f6ce7` require maintainer approval (`action_required`). The fork's independent results do not approve those workflows or constitute an all-green upstream run.

## Diagnostic setup corrections

An initial independent configuration attempted to build the MCL runtime locally and stopped at the missing Cargo dependency; the diagnostic was corrected to upstream's API-only/installed-runtime mode. The first verification invocation also used a PATH-only GoogleTest executable name, preventing its death-test child from finding the executable with `execv`; the command now uses `/usr/bin/gmanticoretest`. Those failed setup attempts are retained in fork Actions history and are excluded from the successful validation counts above. No test cases or performance thresholds were removed to accommodate them.

## Reproduction and raw outputs

- `diagnostic.yml`: complete controlled-comparison workflow.
- `head-replace.yml`: exact workflow for the two current-runtime REPLACE replays; reuses the successful Linux build artifact.
- `head-native.yml`: exact final native/configuration validation workflow, using the same build artifact.
- `controlled-evidence.zip`: all four `.rep`, `.cmp`, CLT logs, status codes and binary versions.
- `controlled-summary.json`: exact wall times and ratios extracted from each `.rep`.
- `summarize-replace.py`: extraction with exact measurement-count and integer-ratio assertions.

- `head-replace-evidence.zip`: both complete current-runtime CLT outputs, version, exit codes and the earlier integration-plan assertion.
- `head-native-evidence.zip`: final 63-test and ten lifecycle/configuration checks with binary version.
- `head-replace-summary.json`: exact times and ratios for both current-runtime replays.
- `integration-before-fix.txt`: the original zero-cache assertion on Linux with MCL installed.
