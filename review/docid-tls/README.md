# Manticore cache review evidence

PR [#5042](https://github.com/manticoresoftware/manticoresearch/pull/5042)
contains the opt-in native DocID cache and shared docstore block-cache sharding
with XXH3. Its current source is `376fbf9988b2458ee196a5d92135c35a5121edc7`.
It contains no reader TLS or global generation counter.
PR [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045)
remains reader TLS only at `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.
Neither PR depends on the other.

- [Shared block cache: final no-TLS results, design and CI fixes](BLOCK_CACHE_2026-11-13.md).
- [Reader TLS: default-cache/large-data results and maintainer answers](TLS_REVIEW_2026-11-13.md).
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

The new #5042 local native suites passed 521/521 in both comparison arms, API
smoke and DocID SQL lifecycle passed, and focused 26-test sanitizer runs passed
20 repeats each. Upstream CI for the pushed commit is awaiting maintainer
approval (`action_required`), not a passing run. See the report for actual scope.

Directory microbenchmark throughput, TLS QPS at a fixed budget, block-cache
implementation changes and cache on/off comparisons answer different questions.
Their gains must not be added or multiplied. All negative/control samples are
retained. MANIFEST.json hashes this published snapshot, excluding itself.
