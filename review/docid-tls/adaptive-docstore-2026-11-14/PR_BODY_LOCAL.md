The native DocID cache accelerates repeated numeric ID-to-row lookup; the separate docstore cache reuses decoded stored-field blocks. This PR now includes the latest opt-in adaptive docstore implementation. Reader registration and lookup remain unchanged; reader TLS is independent in [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045).

| Cache | Setting | Default | Behavior |
| --- | --- | --- | --- |
| Native DocID → RowID | `docid_lookup_cache_size` | `0` | Immutable per-disk-chunk lookup caches; compressed fallback when refused or inapplicable |
| Decoded stored-field blocks | `docstore_cache_size` | `16m` | Shared LRU partitions using seeded XXH3-64 |
| Adaptive block policy | `docstore_cache_adaptive` | `0` | Second-touch admission, gradual cold-entry reclamation, mapped payload storage |

The native DocID cache retains the existing disk format and costs about 11.58 MiB per million entries on the tested hosts; allocation/alignment padding count against its own budget. Chunk remap/destruction releases it. The two cache budgets are independent and server-wide.

The block cache has up to 16 independently locked partitions. A successful lookup/insertion pins the payload; releasing that pin is an atomic decrement, avoiding a second hash lookup and mutex acquisition per returned row. LRU membership and eviction remain locked. Adaptive misses use one fixed 256 KiB atomic fingerprint history: the first visit decodes temporarily, and a repeated fingerprint visit becomes eligible for insertion. Full-key checks preserve correctness despite fingerprint collisions. This reduces first-visit insertion/eviction work without a separate global bypass state.

## 1. Larger budgets extend the useful working-set range

Every performance column below uses **the same cache implementation and binary, `8fec92b`**, with native DocID caching and SQL query caching disabled and **no reader TLS**. Published head `90e8841` changes only CMake test registration; production source is byte-identical. These are cache-configuration comparisons, not full-PR speedups over upstream or comparisons against an early PR implementation.

Apple M4 Pro / Clang 21, `-O2 -DNDEBUG`; eight clients and eight workers; 256 returned rows/query, 128-byte stored text, 16 KiB/LZ4. Random queries reuse 64 deterministic templates per client; each sample warms the complete pool. Six balanced rounds × five seconds/arm; reported QPS and server CPU/query are per-arm medians. All nonzero capacities in this matrix use 16 partitions.

**Multiplier = enabled-cache QPS / cache-off QPS in the same case.** 1.30× means 30% more throughput; 0.90× means 10% less. Lower server CPU/query is better.

QPS (multiplier versus cache off):

| Rows | Off | Default manual 16 MiB | Adaptive 16 MiB | Adaptive 128 MiB | Manual 512 MiB | Adaptive 512 MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20,000 | 6,203.8 (1.00×) | 8,213.0 (1.32×) | 8,224.6 (1.33×) | 8,038.2 (1.30×) | 8,297.8 (1.34×) | 8,056.4 (1.30×) |
| 100,000 | 5,441.6 (1.00×) | 7,330.3 (1.35×) | 7,232.9 (1.33×) | 7,231.5 (1.33×) | 7,278.6 (1.34×) | 7,291.8 (1.34×) |
| 1,000,000 | 3,397.0 (1.00×) | 2,969.2 (0.87×) | 3,024.9 (0.89×) | 5,250.3 (1.55×) | 5,386.9 (1.59×) | 5,334.3 (1.57×) |
| 5,000,000 | 1,759.0 (1.00×) | 1,659.5 (0.94×) | 1,698.8 (0.97×) | 1,763.0 (1.00×) | 2,108.2 (1.20×) | 2,094.2 (1.19×) |
| 20,000,000 | 742.7 (1.00×) | 721.2 (0.97×) | 726.2 (0.98×) | 733.8 (0.99×) | 731.3 (0.98×) | 756.5 (1.02×) |

Server CPU milliseconds/query:

| Rows | Off | Manual 16 MiB | Adaptive 16 MiB | Adaptive 128 MiB | Manual 512 MiB | Adaptive 512 MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20,000 | 1.0896 | 0.8180 | 0.8154 | 0.8357 | 0.8090 | 0.8332 |
| 100,000 | 1.2683 | 0.9345 | 0.9482 | 0.9463 | 0.9429 | 0.9360 |
| 1,000,000 | 2.1540 | 2.4433 | 2.3996 | 1.3655 | 1.3300 | 1.3434 |
| 5,000,000 | 4.3439 | 4.5916 | 4.5111 | 4.3461 | 3.6503 | 3.6697 |
| 20,000,000 | 10.5099 | 10.8362 | 10.7482 | 10.6609 | 10.6904 | 10.3466 |

![Capacity, throughput and CPU/query](capacity.png)

At 20k–100k rows, 16 MiB already covers most reused blocks; allocating a higher ceiling adds little. At 1M, adaptive 16 MiB gives **0.89×**, while 128/512 MiB give **1.55× / 1.57×**. At 5M, adaptive 512 MiB gives **1.19×** and **-15.52% CPU/query** versus off. The sampled benefit is not monotonic in total rows: capacity should follow the active **decoded, reused** working set, rather than compressed table size. The plot shows sampled configurations, not an exact crossover or universal optimum. Raising the ceiling and changing admission policy are separate comparisons; manual/adaptive columns at the same ceiling keep that distinction visible.

## 2. Beyond capacity: reduce churn, retain the remaining losses

At 20M random rows, adaptive 512 MiB achieves **1.019×** cache-off throughput (+1.87%), with **-1.55% CPU/query**. The same-ceiling manual 512 MiB result is **0.985×**. Admission filters first visits; it does not eliminate cache lookup, synchronization, temporary decoding or repeated-visit costs.

| 20M advancing scan | QPS | QPS / off | Server CPU ms/query | CPU vs off |
| --- | ---: | ---: | ---: | ---: |
| off | 5,154.4 | 1.000× | 1.1556 | +0.00% |
| manual512 | 7,521.9 | 1.459× | 0.7569 | -34.50% |
| adaptive512 | 7,545.7 | 1.464× | 0.7566 | -34.53% |

The advancing scan generates new contiguous 256-ID ranges rather than cycling the random query pool. Its results are a separate locality control. Adaptive mode does **not** guarantee cache-off parity: at 1M random rows with only 16 MiB, throughput is still **-10.95%** versus off. A bigger cache can help when it covers reuse; a low-reuse workload can still favor cache off. There is no automatic low-hit-rate switch to cache off.

## 3. A smaller active set releases process memory

Two diagnostic passes retain the same 5M-row table and change only the query access range: **5M broad → 20k hot → 5M broad again**. Each phase runs for eight seconds after warmup. Manual/adaptive order is reversed on the second pass. Values below are medians of the two phase-end snapshots, in MiB; each individual pass and continuous trace is retained.

| Access phase (same 5M-row table) | Manual 512 MiB RSS | Adaptive 512 MiB RSS | Adaptive footprint | Adaptive entries / mapped |
| --- | ---: | ---: | ---: | ---: |
| 5M broad | 772.5 | 767.2 | 689.6 | 511.8 / 660.2 |
| 20k hot | 772.9 | 167.9 | 90.3 | 15.8 / 59.7 |
| 5M broad again | 774.0 | 768.7 | 691.1 | 511.8 / 660.1 |

![Broad/hot/broad memory traces, both passes](memory.png)

Both modes allocate on demand; a 512 MiB ceiling never means an eager 512 MiB reservation. Adaptive mode additionally trims cold, unpinned entries after a stable smaller hot set is observed. Decoded payloads use per-partition OS mappings: small blocks are packed into 64 KiB regions, and empty regions are unmapped; larger blocks use dedicated mappings. Up to one empty 64 KiB region is retained per partition (at most 1 MiB total).

Reclamation advances on lookups, not an idle timer. Pinned blocks and partially occupied regions can retain memory. `docstore_cache_size` caps **charged payload allocation classes plus cached entries**, not total mapped bytes or process RSS. Metadata, fingerprint history, reader/result buffers, temporary first-visit decodes and mapping slack are additional; mapping-failure/oversized fallbacks use the process heap. `docstore_cache_used_bytes`, `docstore_cache_mapped_bytes` and `docstore_cache_spare_bytes` expose the separate quantities.

## Configuration and validation

Existing defaults remain manual 16 MiB and native DocID cache off. Opt in explicitly:

```ini
searchd {
    docstore_cache_size = 512m
    docstore_cache_adaptive = 1
}
```

The implementation passes 548 native gtests, API smoke, and DocID lifecycle checks at 0/1 KiB/16 MiB. Thirty focused cache/pool/admission/reclamation tests pass 20 repetitions each under ASan+UBSan and TSan (600 tests per sanitizer). Instrumentation covers docstore, file I/O and the focused test translation unit; other engine archives are reused uninstrumented. ASan leak detection is disabled on macOS. Previously pushed CI repairs remain included: Windows output types, GoogleTest compatibility, smoke/metric expectations and alignment-safe access. The latest follow-up relocates three test registrations to remove the conflict with newly added upstream suites; it preserves the exact registered test-source set.

GitHub reports the updated PR as mergeable. The [upstream test workflow](https://github.com/manticoresoftware/manticoresearch/actions/runs/43545580359), docs and packaging workflows are `action_required`, awaiting maintainer approval for the fork; the test run has zero executed jobs. This is not a CI pass. Linux/Windows CI and production endurance are not established by this macOS measurement. Cache clear/shutdown retain their existing quiescent-reader preconditions.
