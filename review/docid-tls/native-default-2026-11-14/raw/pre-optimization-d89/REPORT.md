# Native DocID cache: isolated SQL on/off comparison

Latest d89cebc binary; adaptive docstore cache stays at 16 MiB in both arms; native DocID budget is the only changed setting. Native budgets are 0 vs 16 MiB at 1M rows, and 0 vs 128 MiB at 5M rows. Eight clients, six alternating rounds, five seconds per arm. QPS and server CPU/query are per-arm medians. Point queries return one ID; batch queries return 256 rows. All timed responses are checked. Full count has no ID filter and is a control. Startup/construction time is excluded.

| Rows | Query | QPS off → on | QPS ratio | CPU ms/query off → on | CPU change | Native allocation MiB |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1,000,000 | point | 37,507.7 → 37,185.2 | 0.991× | 0.1468 → 0.1487 | +1.25% | 11.57 |
| 1,000,000 | id-only | 8,592.0 → 20,809.4 | 2.422× | 0.8421 → 0.2791 | -66.86% | 11.57 |
| 1,000,000 | stored | 3,005.5 → 3,383.5 | 1.126× | 2.4070 → 2.0055 | -16.68% | 11.57 |
| 1,000,000 | full-count | 48,041.6 → 47,161.1 | 0.982× | 0.0867 → 0.0900 | +3.81% | 11.57 |
| 5,000,000 | id-only | 2,694.8 → 20,030.4 | 7.433× | 2.8884 → 0.2997 | -89.62% | 57.86 |
| 5,000,000 | stored | 1,674.6 → 2,977.7 | 1.778× | 4.5701 → 2.3466 | -48.65% | 57.86 |

Quality-rule flags: 0. Raw sample journals, plans, configurations, query hashes, SQL plans and telemetry are preserved. Query planning can change when a complete DocID cache is admitted; this measures the whole native-cache feature, not the lookup kernel alone.

The cache holds immutable whole-chunk ID/row mappings. Its budget is additional to the docstore cache; it has no hot-entry LRU or lookup-driven shrinking. Chunk unload/remap/destruction releases allocations. These are warm synthetic ID-filter workloads, not a universal gain for full-text, dense predicates or cold startup.
