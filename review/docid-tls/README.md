# Manticore cache review evidence

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
contains the opt-in native DocID cache and shared docstore block-cache sharding
with XXH3. Its current source is `376fbf9988b2458ee196a5d92135c35a5121edc7`.
It contains no reader TLS or global generation counter.
PR [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045)
remains reader TLS only at `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
Neither PR depends on the other.

- [Current opt-in adaptive cache, 512 MiB ceiling](ADAPTIVE_CACHE_2026-11-13.md): system-mapped payloads, packed small-block regions, default/adaptive QPS and CPU tables, and measured process-memory return. This follow-up is on a separate experimental branch, outside both production PRs.
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

The #5042 local native suites passed 521/521 in both comparison arms, API
smoke and DocID SQL lifecycle passed, and focused 26-test sanitizer runs passed
20 repeats each. Upstream CI for the pushed commit is awaiting maintainer
approval (`action_required`), not a passing run. The latest TLS-context pair
separately passed 529/529 each and focused reader/block sanitizers (11 tests ×20
per sanitizer). See the reports for the distinct source and validation scopes.

Directory microbenchmark throughput, TLS QPS at a fixed budget, block-cache
implementation changes and cache on/off comparisons answer different questions.
The #5042 and historical ZIPs remain dated snapshots; the new reader-TLS ZIP
contains the latest-cache context and the paired original/latest report.
Their gains must not be added or multiplied. All negative/control samples are
retained. MANIFEST.json hashes this published snapshot, excluding itself.
