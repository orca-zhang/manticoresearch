# Adaptive docstore cache: current implementation and process-memory return

The current experimental adaptive cache stores decoded payloads in its own
system-mapped regions and releases fully empty regions to the OS. The tables
below compare the current implementation with the published #5042 default
configuration. It reports throughput, CPU per query and observed process
memory through a shrinking and expanding working set.

**Observed result:** two fresh-server passes reduce RSS by about 478 MiB
when the queried range shrinks, then refill successfully. At 500k rows the
longer default-16→adaptive-512 comparison gives +82.26% QPS and -45.00%
CPU/query; this also raises capacity. Small datasets show no established
throughput benefit. Equal-16 changes reverse sign between primary and repeat
runs. **External-load flags affect 78/180 primary samples and 6/72 longer
repeat samples**, so these are descriptive results, not a universal gain or
precise optimum. Every flagged sample remains.

[Current source commit `f5cf080`](https://github.com/orca-zhang/manticoresearch/commit/f5cf080a497d2986336ab514a0fab78536198837),
[raw evidence and plans](evidence/2026-11-13/vm-cache/),
[QPS/CPU comparison CSV](evidence/2026-11-13/vm-cache/summary.csv),
[download evidence](attachments/adaptive-cache-evidence.zip).
The source is a separate opt-in experiment. Production [#5042](https://github.com/manticoresoftware/manticoresearch/pull/5042)
remains `376fbf9`, with no reader TLS; [#5045](https://github.com/manticoresoftware/manticoresearch/pull/5045)
remains TLS-only at `019868e9`. No adaptive-plus-TLS measurement exists.

## What the current implementation improves

- **Decoded payloads bypass heap retention.** POSIX uses anonymous mappings;
  Windows uses `VirtualAlloc`. Compressed blocks decode directly into their
  destination; uncompressed small/large fields are also supported. Metadata,
  temporary compressed input and query output still use the process heap.
- **Small blocks share mapped regions.** Payloads up to 31 KiB use 256-byte
  size classes packed into 64 KiB regions. This avoids rounding each slightly
  over-16-KiB block to 32 KiB on Apple hardware with 16 KiB memory pages.
  Larger payloads use dedicated page-rounded mappings.
- **Empty regions return to the OS.** The last live block frees its region via
  `munmap`/`VirtualFree`, apart from one reusable empty 64 KiB region per shard.
  Sixteen shards retain at most 1 MiB of completely empty spare regions.
  Dedicated large mappings are released immediately. Allocation reuses free
  slots and the empty spare before requesting more mappings.
- **Ownership covers all read paths.** Cache references protect active blocks;
  rejected or duplicate admissions release through the correct allocator.
  Oversized payloads and mapping failures fall back to the process heap.
- **Accounting separates entries, mappings and process memory.** The existing
  used-byte metric charges small slots or large mappings plus LRU nodes.
  New mapped/spare metrics expose backing-region overhead and empty retention.
  RSS and physical footprint are measured independently in the diagnostic.

The cache retains seeded XXH3-64, fixed shard mapping, no reader TLS and no
process-wide generation counter. Each shard observes 4096-lookup windows
under its existing lock. Four windows with >=99% hits and touched bytes below
one quarter of retained bytes permit cold-entry reclamation. It targets twice
recent touched bytes, with a floor totaling up to 16 MiB. At most 32 entries
are inspected per 64 lookups. Referenced or recently touched entries survive.
The floor is a target, not a minimum allocation or guaranteed final occupancy.
Idle shards do not advance this lookup-driven policy.

The experiment remains explicit opt-in:

```ini
docstore_cache_size = 512m
docstore_cache_adaptive = 1
```

Default settings remain 16 MiB/manual. Allocation is already on demand;
`512m` does not reserve 512 MiB at startup. The entry ceiling is not a process
RSS or mapped-address-space ceiling. Partially occupied regions retain unused
slots; these can keep a region mapped until its final live block is freed.
In-flight blocks, bounded empty spares, hash tables, metadata, heap fallbacks
and other engine memory are additional. Virtual mapped bytes are not resident
physical bytes.

## Default configuration versus current adaptive mode

Baseline: the published #5042 shared-cache binary `376fbf9`, manual 16 MiB,
with native DocID and SQL query caches off. Adaptive 16 MiB changes implementation and mode
at the same configured entry ceiling. Adaptive 512 MiB also raises capacity;
its gain must not be attributed solely to the adaptive policy.

Apple M4 Pro / Clang 21 `-O2 -DNDEBUG`; eight clients and eight server workers,
256 returned rows, 128-byte rowwise text, 16 KiB/LZ4, persistent HTTP and an
8 MiB reader-buffer budget. Both cache ceilings use 16 shards. Six balanced
Williams rounds ×3 seconds per arm; one queried arm at a time. Every returned
ID and text value is checked. Each client warms and cycles through 20 fixed
random 256-ID queries (seed 513). These finite pools are not a cold full-table
scan, even on the 5M-row table.

All six server instances remain alive during a matrix group. The transition
diagnostic uses one server at a time; its RSS snapshots and the primary memory
medians therefore describe different process/system states.

Values are medians of six arm samples; changes are ratios of medians. Lower
server CPU milliseconds per completed query is better. Ranges are min/max of
six within-round QPS changes, not confidence intervals. No control subtraction
is applied.

![Current adaptive throughput and sampled size range](figures/adaptive-cache-capacity.png)

### Equal 16 MiB

| Rows | Default QPS | Adaptive QPS | QPS change | Default CPU ms/query | Adaptive CPU ms/query | CPU/query change |
| --- | --- | --- | --- | --- | --- | --- |
| 20,000 | 7,404.1 | 7,456.3 | +0.70% | 0.8810 | 0.8759 | -0.59% |
| 100,000 | 6,819.4 | 6,772.2 | -0.69% | 0.9783 | 0.9729 | -0.55% |
| 500,000 | 3,073.7 | 2,888.4 | -6.03% | 2.1843 | 2.2415 | +2.62% |
| 1,000,000 | 2,690.7 | 2,619.7 | -2.64% | 2.6302 | 2.6592 | +1.10% |
| 5,000,000 | 1,116.3 | 1,155.1 | +3.48% | 5.5137 | 5.4818 | -0.58% |

### Adaptive 512 MiB ceiling

| Rows | Default QPS | Adaptive QPS | QPS change | Default CPU ms/query | Adaptive CPU ms/query | CPU/query change |
| --- | --- | --- | --- | --- | --- | --- |
| 20,000 | 7,404.1 | 7,456.3 | +0.70% | 0.8810 | 0.8693 | -1.34% |
| 100,000 | 6,819.4 | 6,755.3 | -0.94% | 0.9783 | 0.9898 | +1.18% |
| 500,000 | 3,073.7 | 5,784.0 | +88.18% | 2.1843 | 1.1625 | -46.78% |
| 1,000,000 | 2,690.7 | 4,545.0 | +68.92% | 2.6302 | 1.5271 | -41.94% |
| 5,000,000 | 1,116.3 | 1,732.5 | +55.20% | 5.5137 | 3.9468 | -28.42% |

The 512 MiB comparison changes capacity as well as mode. Its sampled curve
locates useful operating points for this query pool, not a universal dataset
size optimum. Projection width, decoded-block reuse and concurrency determine
the working set. Internal equal-512 controls and the VM-16→512 comparison are
retained in the CSV for attribution. Gains from separate comparisons must not
be added or multiplied. All negative results remain.

![Current server CPU/query and longer checks](figures/adaptive-cache-policy.png)

### Preselected longer repeats

Fresh servers, six balanced rounds ×5 seconds per arm at 20k and 500k. These
sizes were selected before the final packed-region run, not from its results.

| Rows | Adaptive 16 QPS change | CPU/query change | Adaptive 16 paired QPS range | Adaptive 512 QPS change | CPU/query change |
| --- | --- | --- | --- | --- | --- |
| 20,000 | -2.18% | +1.71% | -7.98% … +0.91% | -0.33% | +0.90% |
| 500,000 | +1.35% | -0.97% | -1.06% … +3.08% | +82.26% | -45.00% |

## Process memory returned to the OS

The diagnostic uses the same 5M-row table, first querying a broad 5M ID range,
then a 20k hot prefix, then the broad range again. Each stage warms its pool
and runs eight timed seconds. Two fresh-server passes reverse internal
control/current arm order. Status/RSS/footprint probes run every 0.2 seconds;
this is a memory diagnostic, not the primary QPS comparison. Phase widths in
the figure are normalized; raw timestamps remain in JSON.

![Current adaptive cache and process-memory return](figures/adaptive-cache-working-set.png)

| Pass | Stage | Charged entries MiB | Mapped regions MiB | Empty spares MiB | Process RSS MiB | Physical footprint MiB |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | large | 411.21 | 529.62 | 0.00 | 633.19 | 555.42 |
| 1 | hot | 15.80 | 50.75 | 1.00 | 155.33 | 77.56 |
| 1 | large-again | 412.17 | 530.81 | 0.00 | 635.52 | 557.77 |
| 2 | large | 411.21 | 529.62 | 0.00 | 631.05 | 553.27 |
| 2 | hot | 15.80 | 50.19 | 1.00 | 153.11 | 75.33 |
| 2 | large-again | 412.17 | 530.81 | 0.00 | 633.89 | 556.11 |

Pass 1: broad→hot RSS changes by -477.86 MiB; mapped address space changes by -478.88 MiB. The final broad stage reaches 635.52 MiB RSS after refilling.

Pass 2: broad→hot RSS changes by -477.94 MiB; mapped address space changes by -479.44 MiB. The final broad stage reaches 633.89 MiB RSS after refilling.

These are observed process RSS/footprint values, separate from cache-entry
counters. The kernel release calls are checked, and no process-global heap
trim/purge is invoked. The pool cannot release a partially occupied region;
remaining fragmentation and unrelated heap allocations explain why entry bytes,
mapping bytes and RSS need not converge to the same value. The run does not
establish behavior under memory pressure, after a fully idle workload, or on
Linux/Windows allocators.

`docstore_cache_used_bytes` reports charged retained entries;
`docstore_cache_mapped_bytes` reports all pool virtual mappings, including
partially occupied regions and in-flight blocks; `docstore_cache_spare_bytes`
reports only completely empty retained regions. Snapshots use separate locks
and are not globally atomic. Heap-fallback storage is absent from mapped/spare
metrics. Monitoring overhead at production polling rates is unmeasured.

### Primary memory medians

| Rows | Default RSS MiB | Adaptive 16: entry / mapped / RSS MiB | Adaptive 512: entry / mapped / RSS MiB |
| --- | --- | --- | --- |
| 20,000 | 31.77 | 2.53 / 3.62 / 32.40 | 2.53 / 3.62 / 33.16 |
| 100,000 | 47.23 | 12.65 / 16.75 / 48.05 | 12.65 / 16.75 / 46.48 |
| 500,000 | 81.54 | 15.80 / 22.00 / 55.45 | 63.24 / 81.69 / 112.49 |
| 1,000,000 | 76.04 | 15.81 / 22.00 / 67.05 | 126.01 / 162.81 / 207.38 |
| 5,000,000 | 121.04 | 15.80 / 22.00 / 115.84 | 411.21 / 529.62 / 513.42 |

## Load control, raw data and interpretation limits

Each group waits for a continuous 30-second idle gate: mean >=90%, minimum
interval >=80%. One-second CPU telemetry covers every timed interval fully.
External CPU is estimated for surviving processes outside benchmark process
trees; short-lived processes can be missed. A flag means sample-average
external CPU >10% of machine capacity or any overlapping interval >20%.
Flags are annotations, not exclusion rules or proof of causation. CPU placement,
frequency and desktop activity remain uncontrolled. No confidence interval or
universal no-regression guarantee is claimed.

| Phase | Timed arm samples | Checked timed queries | Load-flagged samples | Diagnostic stage samples | Checked diagnostic queries | Diagnostic flags |
| --- | --- | --- | --- | --- | --- | --- |
| matrix | 180 | 2,536,939 | 78 | 12 | 381,473 | 7 |
| repeat | 72 | 2,225,439 | 6 | 0 | 0 | 0 |

| Phase | Rows | Flagged arm samples / total |
| --- | --- | --- |
| matrix | 20,000 | 1 / 36 |
| matrix | 100,000 | 2 / 36 |
| matrix | 500,000 | 17 / 36 |
| matrix | 1,000,000 | 25 / 36 |
| matrix | 5,000,000 | 33 / 36 |
| repeat | 20,000 | 4 / 36 |
| repeat | 500,000 | 2 / 36 |

Per-arm/per-round external-CPU means, peaks, flags and telemetry coverage are retained in `summary.json` and the raw logs. No flagged sample is excluded. In particular, the primary 5M group is heavily load-affected and does not establish a precise gain or optimum.

The primary table has six internal arms: published default 16 MiB; equal-512
manual/adaptive heap controls; current adaptive 16/512 MiB; and current cache
off. Those controls help separate capacity and allocator effects, and remain
in raw JSON/CSV. They are not presented as separate versions in the main
comparison. Every completed final sample is retained, including per-arm
journals that survive an interrupted case. The plan was written before final
results. The summarizer checks exact driver/source hashes, journals, medians,
ratios, paired ranges, ceiling bounds, lifecycle checks and full telemetry.

An initial per-entry mapping diagnostic exposed page-rounding amplification:
slightly over-16-KiB blocks consumed 32-KiB mappings on this machine. Its four
fully completed case groups and interruption record are retained under
`pre-packing-diagnostic/`. It was stopped during the 5M group; that interrupted
group's partial samples were not persisted. Final results were fully recollected
after packing, with a regression test for a 100k-row working set at 16 MiB.
This diagnostic is not pooled into the final comparisons.

## Validation and source scope

Current source is `f5cf080a497d2986336ab514a0fab78536198837`. The measured searchd SHA256 is
`96403c25079f46ea3cc1603a4e0f52aa1e542944589e0d69ef10e74f4bb87e50`. All six affected translation units were
recompiled with the recorded Clang 21 commands; changed archive objects replace
original objects and unchanged engine/dependencies are reused. Exact commands,
source snapshots, patch, hashes and calibration exports are in the evidence.

- Full native suite: **537/537 passed**.
- Focused native, ASan+UBSan and TSan: **19 tests ×20 each passed**.
- Tests cover packing above a page boundary, reuse, excess-region release,
  concurrent allocation/release, pinned cache references, stored-field
  reclamation, uncompressed small/large fields, tiny-budget fallback and the
  full 100k-row/128-byte working set fitting the default 16 MiB entry budget.
- API smoke passes with the mapped/spare metric golden. The pinned-Buddy exact
  metric exclusions are extended for metrics that Buddy does not yet export.
- Every timed response and post-timing REPLACE/flush/DROP/recreate check passes;
  native DocID used bytes are checked as zero.

Sanitizers instrument docstore, SkipCache, file I/O and focused tests; other
linked libraries are reused uninstrumented. This is not whole-engine sanitizer
coverage. Custom mapped slots do not acquire normal per-allocation heap redzones.
LeakSanitizer is unsupported on this macOS runtime; ASan uses `detect_leaks=0`.
Supported stack-calibration overrides are inherited from the earlier Clang 21
build; no fresh automatic calibration is claimed. Generic LRU epoch metadata
remains part of the experiment even in manual mode; SkipCache throughput is
unmeasured. Mapped-region fields add metadata to cached block values.

The experimental branch is separate from production #5042/#5045. Local test
success is not upstream CI success. [#5042 run 43408089087](https://github.com/manticoresoftware/manticoresearch/actions/runs/43408089087)
was rechecked during this review: `action_required`, zero jobs, awaiting
maintainer fork-workflow approval. No new Linux/Windows CI result,
adaptive-plus-TLS result or cold-storage/memory-pressure result is established.

[Reproduction guide](repro/2026-11-13/README.md#adaptive-cache-follow-up).
