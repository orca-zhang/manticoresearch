# Performance evidence and reporting boundaries

All percentages below identify their reference. Directory lookup throughput and
SQL QPS are different metrics. Improvements from the two patches must not be
added or multiplied; the affected query paths and baselines differ.

## 1. DocID cache-line directory isolation

Reference: fixed-16-child native cache prototype with stack scratch. Candidate:
current adaptive native cache with the same scratch policy. This is a comparison
within the new cache, not against upstream compressed lookup and not SQL QPS.
Intel N100 / 64 B cache lines / GCC 11.4 `-O3`, 100k and 1M documents, five
rotated rounds with five thread-CPU samples/case. Batch API calls have 16 probes.

| Order | Documents | Batch gain: 0 / 50 / 100% misses | Scalar gain: 0 / 50 / 100% misses |
| --- | ---: | --- | --- |
| sorted | 100,000 | +22.22% / +24.39% / +25.74% | +27.64% / +29.60% / +30.21% |
| sorted | 1,000,000 | +18.82% / +19.85% / +19.56% | +40.64% / +35.53% / +31.65% |
| random | 100,000 | +25.08% / +20.76% / +27.17% | +20.44% / +27.29% / +25.73% |
| random | 1,000,000 | +12.58% / +11.05% / +14.96% | +53.60% / +55.55% / +43.30% |

The 128 B Apple M4 Pro keeps 16 children; no consistent improvement is established
there (batch samples span -4.93% to +3.60%). No current Linux/N100 SQL QPS
measurement exists for directory adaptation. The exact source hashes, compiler
manifests and full negative/control data are included in `evidence/stack-scratch-*`.
The raw historical three-arm run also contains temporary-array TLS; only the
fixed16+stack and adaptive+stack arms contribute to this directory comparison.

Memory at 1M documents:

| Host | Fixed16 prototype | Adaptive candidate | Difference |
| --- | ---: | ---: | ---: |
| N100 / 64 B | 12,133,887 B | 12,143,295 B | +9,408 B (+0.078%) |
| M4 Pro / 128 B | 12,134,015 B | 12,134,015 B | 0 |

These are requested allocation bytes, not RSS. The whole DocID cache is extra
memory beside existing mapped data (about 11.58 MiB per million entries on N100).
Its default budget is zero; budgets include handles and alignment slack. No
overall memory saving is claimed for alignment or for adding the native cache.

## 2. TLS on an independent upstream baseline

Primary comparison: upstream `047d2f9` versus the same source plus patch 2.
The DocID prototype is absent from both binaries. Same copied 20k-row disk
snapshot, 128 B stored text, 16 KiB blocks, LZ4, `threads=8`, 1/8 persistent
HTTP connections, four alternating two-second rounds per arm. Every returned
field is checked. Both query plans and binary hashes are captured in the JSON.

**Within every row, both binaries use the same block-cache budget.** The QPS
ratio measures TLS at that budget; it does not compare disabling versus enabling
block caching. QPS change is `median(after)/median(before)-1`. CPU/query change
uses the analogous server CPU ratio.

| Block cache | Clients | Rows | Projection | Before QPS | TLS QPS | QPS change | CPU/query change |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 0 | 1 | 1 | stored text | 8,380 | 8,697 | +3.78% | -1.81% |
| 0 | 1 | 64 | stored text | 2,920 | 2,971 | +1.74% | -1.21% |
| 0 | 1 | 256 | stored text | 1,026 | 1,036 | +0.99% | -1.09% |
| 0 | 1 | 256 | count | 3,607 | 3,537 | -1.94% | -0.86% |
| 0 | 8 | 1 | stored text | 27,849 | 29,801 | +7.01% | -2.80% |
| 0 | 8 | 64 | stored text | 11,543 | 11,603 | +0.52% | -4.03% |
| 0 | 8 | 256 | stored text | 4,049 | 4,336 | +7.09% | -5.20% |
| 0 | 8 | 256 | count | 14,818 | 14,918 | +0.67% | -2.96% |
| 16 MiB | 1 | 1 | stored text | 7,921 | 8,560 | +8.07% | -3.16% |
| 16 MiB | 1 | 64 | stored text | 3,778 | 3,758 | -0.54% | +0.62% |
| 16 MiB | 1 | 256 | stored text | 1,345 | 1,296 | -3.63% | +0.37% |
| 16 MiB | 1 | 256 | count | 3,551 | 3,357 | -5.47% | +1.96% |
| 16 MiB | 8 | 1 | stored text | 33,770 | 35,405 | +4.84% | -1.09% |
| 16 MiB | 8 | 64 | stored text | 10,661 | 10,585 | -0.71% | +0.53% |
| 16 MiB | 8 | 256 | stored text | 2,879 | 2,916 | +1.30% | +1.07% |
| 16 MiB | 8 | 256 | count | 18,136 | 18,660 | +2.89% | +0.75% |

### Targeted repeat and interpretation

The 8-client/256-row/cache-disabled case and count control were repeated with
six alternating three-second rounds per arm, after the main run and without
concurrent builds/tests.

| Projection | Before QPS | TLS QPS | QPS change | CPU/query change |
| --- | ---: | ---: | ---: | ---: |
| stored text | 4,568 | 5,217 | +14.20% | -8.48% |
| count | 16,514 | 16,450 | -0.39% | -0.49% |

The 256-row targeted workload shows a benefit in both runs, but magnitude varies.
The 64-row case is only +0.52% QPS in the primary run, so a stable gain there
is not established. Warm-block-cache and point/count controls vary too; in the
primary run the warm single-client point case is +8.07% and the warm count
case is -5.47%, despite bypassing reader lookups. Do not attribute such controls
to mutex savings or claim universal benefit. These short local samples do not
provide a production confidence interval or a zero-regression guarantee.

The earlier +8.02%–11.24% results came from paired builds with the DocID
prototype enabled at the same budget in both arms. They are retained under
`evidence/reader-tls-m4/` for traceability, but are not the primary independent
upstream claim. Different fixtures/builds/runs cannot quantify the separate
effect of DocID by subtraction.

A separate diagnostic run in that prior combined environment observed 98.59%
of reader lookups avoiding the mutex at eight clients/256 rows with block
caching disabled, and no additional reader lookups after full block-cache
warmup. Those counters were absent from timed binaries; this is a diagnostic
observation with its own scheduling, not an exact lock-hit prediction for the
fresh upstream run.

TLS costs 32 B per OS thread (256 B at eight threads) plus runtime metadata;
the shared generation adds 8 B. Reader ownership, immediate cleanup and the
existing 8 MiB reader-buffer budget remain intact. Cold lookups add checks/TLS
writes; mutation increments invalidate other sessions. No process-memory saving
is claimed. Cache-line padding of this TLS entry is not included.

The packaged raw JSON also records server/client CPU and memory snapshots.
These snapshots are not a controlled RSS study. Clients share the server host;
rates are fixed-concurrency throughput, not maximum sustainable capacity, p99
latency, cold-disk behavior or a production workload mix. Linux TLS SQL QPS and
full Linux engine/SQL tests remain unmeasured.
