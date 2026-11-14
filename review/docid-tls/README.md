# Manticore cache review evidence

## Latest adaptive docstore measurement (2026-11-14)

The [current #5042 report](adaptive-docstore-2026-11-14/REPORT.md) connects
capacity, oversized working sets and process-memory return using one cache
implementation, with native DocID caching and reader TLS excluded from the
throughput matrix. It presents cache off, adaptive 16/128/512 MiB and a
fixed 512 MiB reference control at 20k–20M rows. Adaptive 16 MiB is now the
default: `docstore_cache=1` enables the adaptive implementation and `0`
disables it; `docstore_cache_size` remains the capacity ceiling.
The report retains every original/confirmation sample, QPS and CPU/query,
an advancing scan and A/A control, and two broad/hot/broad memory passes.
The latest adaptive implementation is now included in #5042; this is no
longer an experiment outside that PR.

[Download the current evidence ZIP](attachments/adaptive-docstore-final-20261114.zip)
(264 timed samples, 6,515,205 checked timed queries, memory traces, source patches
and validation logs; SHA-256 `7a6f0c5cdee535f2aee056927a5481d5f2bd81bae490690a8fcb44d953587b22`).

## Latest independent reader TLS measurement (2026-11-14)

The [standalone #5045 report](independent-tls-2026-11-14/REPORT.md) compares
upstream `047d2f9` with only the reader TLS diff from `019868e9`. Both arms
retain the original upstream block cache; #5042 and adaptive-cache changes
are excluded. It covers 20k/1M/10M rows, default 16 MiB and cache off,
64/256-row retrieval, point/mixed session churn, count and A/A controls.
All 216 timed samples, CPU/query tables, build-isolation hashes and the
scale plot are retained. Default-cache 256-row QPS changes are -0.40% to
+0.61%; the 20k cache-off result is +13.09% QPS / -10.31% CPU/query.

PR [#5042](https://github.com/manticoresoftware/manticoresearch/pull/5042)
contains the opt-in native DocID cache, shared XXH3 block-cache partitions,
atomic pin release and adaptive admission/mapped-memory reclamation.
Its current source is `d89cebcdbee5eeaa205b6a861067b0d1219e6ea3`; the measured
production implementation is `8fec92b21c2f10f720f0bcbca498c5f8179f7ac0`.
Follow-ups remove the upstream test-registration conflict and replace the
policy selector with a default-on cache enable switch. Cache algorithms match
the recorded adaptive measurements; fixed controls are not server options.
It contains no reader TLS or global generation counter.
PR [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045)
remains reader TLS only at `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
Neither PR depends on the other.

- [Earlier adaptive-cache experiment, 512 MiB ceiling](ADAPTIVE_CACHE_2026-11-13.md): historical mapped-payload measurements before the latest admission/pin-release integration. Use the current report above for #5042.
- [Adaptive experiment ZIP](attachments/adaptive-cache-evidence.zip), including every primary/repeat sample, both memory passes, source snapshots and validation logs.
- [Added cache OFF / 8 / 16 MiB matrix, with separate reader-TLS combinations](BLOCK_CACHE_BUDGETS_2026-11-13.md): absolute QPS, negative results, controls and load telemetry.
- [Budget supplement ZIP](attachments/block-cache-budget-evidence.zip), including exact archived drivers and every new sample.
- [Shared block cache: final no-TLS results, design and CI fixes](BLOCK_CACHE_2026-11-13.md).
- [Reader TLS: original and latest block-cache datasets side by side](TLS_REVIEW_2026-11-13.md), with default-cache/large-data results and maintainer answers.
- [Historical original-cache TLS report](TLS_ORIGINAL_CACHE_2026-11-13.md).
- [Latest-context TLS evidence ZIP](attachments/reader-tls-latest-block-cache-evidence.zip).
- [Performance](PERFORMANCE.md), [validation](VALIDATION.md) and
  [design notes](DESIGN_NOTES.md) retain and distinguish the earlier evidence.
- [Current reproduction guide](repro/2026-11-13/README.md) and
  [original reproduction guide](repro/README.md).
- `evidence/2026-11-13/`: raw arm samples, commands, source/binary hashes,
  sanitizer/build/test logs and CI state. `patches/`: exact dated patches.
- [Current shared-block-cache evidence ZIP](attachments/shared-block-cache-evidence.zip).
  [Historical Nov 13 snapshot](attachments/2026-11-13-historical-evidence.zip)
  retains prototype raw phases and English reports, including block-cache
  experiments with TLS in both arms. Those are not final #5042 measurements.
- The original [DocID ZIP](attachments/docid-cache-evidence.zip) and
  [reader TLS ZIP](attachments/reader-tls-evidence.zip) are dated snapshots.

The current #5042 implementation passes 548 native gtests, API smoke and DocID
SQL lifecycle; focused 30-test ASan+UBSan and TSan suites pass 20 repeats each.
The latest enable switch also passes six real-server configuration cases,
with default and explicit enable verified through mapped payload allocation.
The CMake-only follow-up removes the new upstream test-registration conflict.
Upstream CI for the pushed head is awaiting maintainer approval
(`action_required`, zero executed jobs), not a passing run. The earlier shared
cache comparison passed 521/521 per arm. The latest TLS-context pair
separately passed 529/529 each and focused reader/block sanitizers (11 tests ×20
per sanitizer). See the reports for the distinct source and validation scopes.

Directory microbenchmark throughput, TLS QPS at a fixed budget, block-cache
implementation changes and cache on/off comparisons answer different questions.
The #5042 and historical ZIPs remain dated snapshots; the new reader-TLS ZIP
contains the latest-cache context and the paired original/latest report.
Their gains must not be added or multiplied. All negative/control samples are
retained. MANIFEST.json hashes this published snapshot, excluding itself.
