# DocID cache and docstore TLS review evidence

This directory contains the performance evidence, raw samples, regression logs
and reproduction tools for two independent Manticore Search changes:

- Native DocID/cache-line optimization: [PR #5042](https://github.com/manticoresoftware/manticoresearch/pull/5042), [source commit](https://github.com/orca-zhang/manticoresearch/commit/9144f7656dfb995da50df7817b9f8f43ada4b399).
- Docstore reader-map TLS cache: [source commit](https://github.com/orca-zhang/manticoresearch/commit/019868e9f79d1bb2bd1f96dafb88ef20acd45418).

The source trees match the independently validated patches. Local GoogleTest
results were 517/517 for DocID and 496/496 for TLS. The combined tree passed
522/522 with its own supported stack-calibration overrides; the first direct
combined run's JSON death-test SIGBUS is retained in the validation record.

- [Performance report](PERFORMANCE.md): explicit baselines, all control/negative cases, SQL QPS versus lookup throughput and memory costs.
- [Validation record](VALIDATION.md): build/test scope and remaining platform coverage.
- [Design notes](DESIGN_NOTES.md): cache ownership, lifetime and query paths.
- [Reproduction tools](repro/README.md): independent upstream SQL and layout comparisons.
- [DocID evidence ZIP](attachments/docid-cache-evidence.zip) and [TLS evidence ZIP](attachments/reader-tls-evidence.zip): standalone reports and reproduction tools for each review.
- `evidence/`: raw data, source/binary hashes and logs; `patches/`: exact tested patches.

In each TLS comparison, both arms have the same block-cache budget. Directory
microbenchmark percentages are not SQL QPS. The two changes' gains must not be
added or multiplied. MANIFEST.json records this evidence snapshot's hashes.
