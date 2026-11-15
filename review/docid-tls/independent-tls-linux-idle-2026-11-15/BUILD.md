# Build provenance and idle retest reproduction

This is the November 15, 2026 (Asia/Shanghai) independent reader-TLS retest on Linux/x86-64. It reuses the exact executables and deterministic fixtures from the [original Linux build](https://github.com/orca-zhang/manticoresearch/blob/b3b5122cbaa1bbb33fe0eb68e4df3d5a7a87af09/review/docid-tls/independent-tls-linux-2026-11-14/BUILD.md). The source/build manifests, compiler/package configuration, exact production/common-test patches, native test logs and original raw evidence remain available there.

## Identities

- Upstream source: `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`.
- TLS production patch: `src/docstore.cpp` from PR #5045 head `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
- Baseline binary SHA-256: `0fceb502694c975e53d2b432edefd7a13b83ba5b5fb9f342d0957a5ef489ca97`.
- TLS binary SHA-256: `12441ce3bcfb257a308db876a4fa7b54d4bab811bf60a359ef9d52ccb5fe1163`.
- Same five reader tests installed before building either arm; same build worktree/version headers and dependencies. Only `src/CMakeFiles/lmanticore.dir/docstore.cpp.o` differs among 332 recorded objects.
- Both binaries previously passed all 497 native tests and five reader tests repeated 20 times per arm. This retest does not rebuild binaries or claim another fresh sanitizer run.
- Both retain the upstream single-lock CRC32 block cache. No #5042 production code, adaptive cache, sharding, XXH3 block-cache change, native DocID cache or allocator changes are present.

`resume-20261115.json` records a fresh check of binary and complete fixture-file hashes against the prior manifests. `reference-results.json` retains the earlier case/query/binary identities for validation. Earlier performance values are never used as either arm of this retest.

## Service control and load protocol

At the user's explicit instruction, the host-side `run-with-restore.sh` temporarily stops `zimaos-search.service` and `zimaos-photos.service`. Its exit handler starts both services after the benchmark succeeds or fails. Service-state/timestamp logs retain the actual transitions. It is a host-specific control script; a dedicated idle benchmark host can run the Python orchestration directly. No governor, affinity, quota or global page-cache settings are changed.

The policy was fixed before any timed sample: a 30-second gate before each case requires mean idle ≥85% and minimum idle ≥70%. Timed intervals are flagged if estimated external CPU exceeds 15% mean or 30% one-second peak of machine capacity. Every affected complete primary comparison is repeated once in full, retaining all originals. There is no round selection by QPS. The external residual is conservative: CPU of newly started/already-exited benchmark descendants can be missed by the process snapshots. Paired load balance and round-wise dispersion are reported alongside absolute thresholds.

`prepare_idle.py` changes the earlier driver's load thresholds and metadata, asserts the query-pool/timed-measurement regions are byte-identical, and verifies binary/fixture identities. `idle-policy.patch` shows that exact policy change. The first November 14 idle check produced zero timed samples and is retained under `preflight-20261114`; the November 15 search-only-stop check also contains telemetry but no performance samples.

## Primary matrix and diagnostics

`run_idle.py` runs 19 complete comparisons with the original CPython HTTP client (1/8 clients), then four complete 32-client comparisons with matched single-write HTTP framing in both arms. Request bytes are identical; client selfchecks verify framing; no request retries or ignored errors are added. The single-write framing is retained from the earlier Linux comparison so the primary paired protocol remains comparable.

The merger preserves complete cases with their original journals, source phase and driver hashes. Both primary phases use the same binary hashes and deterministic query pools. Six balanced alternating AB/BA rounds ×5 seconds/arm, eight server workers, complete query-pool warmup, and exact response validation apply throughout. Stored-field queries create/clean up query-scoped docstore sessions even on HTTP keep-alive connections.

After any load-triggered full repeats, four additional original-framing 32-client point diagnostics run separately: upstream/TLS and upstream/upstream A/A, each at 16 MiB and disabled block cache. Earlier HTTP failures are retained in the original experiment. Every new diagnostic attempt preserves its completed intervals/logs whether it completes or fails. A/A uses separate executable symlinks to the same baseline binary; actual per-label binary hashes are recorded. A successful diagnostic does not establish the cause of the earlier error.

The primary 1/8/32-client counts use different client framing at 32 and therefore are not a single transport-identical scaling curve. Diagnostic results are listed separately.

## Fresh measurement

Use a fresh workspace mounted under `/work`, with the pinned binaries, source build evidence and fixtures retained from the original build. Never overwrite an existing artifact directory. The original large source/dependency/fixture archives and executables remain on the Linux SSD; public evidence contains their identities and audit records rather than those binaries/private dependency files.

```sh
python3 /work/prepare_idle.py
python3 /work/idle-20261114/driver/run_tls.py --selfcheck
python3 /work/idle-20261114/driver/load_telemetry.py
python3 /work/idle-20261114/driver/coalesced_http.py
python3 /work/idle-20261114/driver/selfcheck_warmup.py
python3 /work/idle-20261114/run_idle.py
```

`prepare_idle.py` expects the original driver/build assets beside it and creates `/work/idle-20261114`; `run_idle.py` expects fixtures at `/work/fixtures`. Executable symlinks point at `/work/searchd-baseline` and `/work/searchd-tls`. It stops on a primary case error rather than silently changing the transport. The benchmark uses Python 3.12 standard-library modules only. The single-write implementation overrides a private CPython method and must be rechecked on Python upgrades.

## Saved report regeneration

Extract the evidence, install Matplotlib, and run from the artifact root:

```sh
python3 driver/make_idle_report.py . report
```

The renderer verifies journal/summary equality, sample counts and medians, percentage/ratio arithmetic, completed lifecycle checks, primary/repeat binary identities, query identity against the earlier run, all primary idle gates, and actual A/A binary equality. It writes the English report, PNG/SVG chart, `summary.csv` and `samples.csv`. All complete comparisons and recorded diagnostic intervals are included; failed intervals without completed aggregates remain logs rather than fabricated samples. Reporting helpers are separate from the measured runtime driver versions.
