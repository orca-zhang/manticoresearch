from pathlib import Path
import json
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
p=Path('/private/tmp/manticore-block-cache-evidence-20261113/review/docid-tls')
d=json.loads((r/'summary.json').read_text());main,repeat=d['phases'];meta=json.loads((r/'build-manifest.json').read_text());commit=meta['source_commit']
parts=[]
def add(s):parts.append(s.strip()+'\n')
def table(head,rows):add('| '+' | '.join(head)+' |\n| '+' | '.join(['---']*len(head))+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows))
def f(n):return f'{n:,.1f}'
def pct(n):return f'{n:+.2f}%'
add(f'''# Adaptive docstore cache: current implementation and process-memory return

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

[Current source commit `{commit[:7]}`](https://github.com/orca-zhang/manticoresearch/commit/{commit}),
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
''')
for arm,pair,label in [('vm_adaptive16','default_to_adaptive16','Equal 16 MiB'),('vm_adaptive512','default_to_adaptive512','Adaptive 512 MiB ceiling')]:
 add('### '+label)
 table(['Rows','Default QPS','Adaptive QPS','QPS change','Default CPU ms/query','Adaptive CPU ms/query','CPU/query change'],[[f"{c['rows']:,}",f(c['arms']['default16']['qps_median']),f(c['arms'][arm]['qps_median']),pct(c['comparisons'][pair]['qps_change_percent']),f"{c['arms']['default16']['server_cpu_ms_per_query_median']:.4f}",f"{c['arms'][arm]['server_cpu_ms_per_query_median']:.4f}",pct(c['comparisons'][pair]['cpu_query_change_percent'])] for c in main['cases']])
add('''The 512 MiB comparison changes capacity as well as mode. Its sampled curve
locates useful operating points for this query pool, not a universal dataset
size optimum. Projection width, decoded-block reuse and concurrency determine
the working set. Internal equal-512 controls and the VM-16→512 comparison are
retained in the CSV for attribution. Gains from separate comparisons must not
be added or multiplied. All negative results remain.

![Current server CPU/query and longer checks](figures/adaptive-cache-policy.png)

### Preselected longer repeats

Fresh servers, six balanced rounds ×5 seconds per arm at 20k and 500k. These
sizes were selected before the final packed-region run, not from its results.
''')
table(['Rows','Adaptive 16 QPS change','CPU/query change','Adaptive 16 paired QPS range','Adaptive 512 QPS change','CPU/query change'],[[f"{c['rows']:,}",pct(c['comparisons']['default_to_adaptive16']['qps_change_percent']),pct(c['comparisons']['default_to_adaptive16']['cpu_query_change_percent']),f"{pct(min(c['comparisons']['default_to_adaptive16']['paired_qps_changes_percent']))} … {pct(max(c['comparisons']['default_to_adaptive16']['paired_qps_changes_percent']))}",pct(c['comparisons']['default_to_adaptive512']['qps_change_percent']),pct(c['comparisons']['default_to_adaptive512']['cpu_query_change_percent'])] for c in repeat['cases']])
add('''## Process memory returned to the OS

The diagnostic uses the same 5M-row table, first querying a broad 5M ID range,
then a 20k hot prefix, then the broad range again. Each stage warms its pool
and runs eight timed seconds. Two fresh-server passes reverse internal
control/current arm order. Status/RSS/footprint probes run every 0.2 seconds;
this is a memory diagnostic, not the primary QPS comparison. Phase widths in
the figure are normalized; raw timestamps remain in JSON.

![Current adaptive cache and process-memory return](figures/adaptive-cache-working-set.png)
''')
vm=[t for t in main['transitions'] if t['arm']=='vm_adaptive512']
table(['Pass','Stage','Charged entries MiB','Mapped regions MiB','Empty spares MiB','Process RSS MiB','Physical footprint MiB'],[[t['pass_number'],q['name'],f"{q['cache_after']['used_bytes']/2**20:.2f}",f"{q['cache_after']['mapped_bytes']/2**20:.2f}",f"{q['cache_after']['spare_bytes']/2**20:.2f}",f"{q['usage_after']['rss_bytes']/2**20:.2f}",f"{q['usage_after']['footprint_bytes']/2**20:.2f}"] for t in vm for q in t['phases']])
for t in vm:
 a,b,c=t['phases'];add(f"Pass {t['pass_number']}: broad→hot RSS changes by {(b['usage_after']['rss_bytes']-a['usage_after']['rss_bytes'])/2**20:+.2f} MiB; mapped address space changes by {(b['cache_after']['mapped_bytes']-a['cache_after']['mapped_bytes'])/2**20:+.2f} MiB. The final broad stage reaches {c['usage_after']['rss_bytes']/2**20:.2f} MiB RSS after refilling.")
add('''These are observed process RSS/footprint values, separate from cache-entry
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
''')
table(['Rows','Default RSS MiB','Adaptive 16: entry / mapped / RSS MiB','Adaptive 512: entry / mapped / RSS MiB'],[[f"{c['rows']:,}",f"{c['arms']['default16']['rss_bytes_median']/2**20:.2f}"]+[f"{c['arms'][n]['cache_median']['used_bytes']/2**20:.2f} / {c['arms'][n]['cache_median']['mapped_bytes']/2**20:.2f} / {c['arms'][n]['rss_bytes_median']/2**20:.2f}" for n in ['vm_adaptive16','vm_adaptive512']] for c in main['cases']])
add('''## Load control, raw data and interpretation limits

Each group waits for a continuous 30-second idle gate: mean >=90%, minimum
interval >=80%. One-second CPU telemetry covers every timed interval fully.
External CPU is estimated for surviving processes outside benchmark process
trees; short-lived processes can be missed. A flag means sample-average
external CPU >10% of machine capacity or any overlapping interval >20%.
Flags are annotations, not exclusion rules or proof of causation. CPU placement,
frequency and desktop activity remain uncontrolled. No confidence interval or
universal no-regression guarantee is claimed.
''')
table(['Phase','Timed arm samples','Checked timed queries','Load-flagged samples','Diagnostic stage samples','Checked diagnostic queries','Diagnostic flags'],[[q['name'],q['timed_arm_samples'],f"{q['timed_queries']:,}",q['load_flagged_samples'],q['diagnostic_samples'],f"{q['diagnostic_queries']:,}",q['diagnostic_load_flagged_samples']] for q in d['phases']])
flags=[]
for phase in d['phases']:
 for case in phase['cases']:
  for name,arm in case['arms'].items():
   for s in arm['sample_load']:
    if s['elevated_external_load']:flags.append([phase['name'],f"{case['rows']:,}",name,s['round'],f"{s['external_cpu_percent_machine_mean']:.2f}%",f"{s['external_cpu_percent_machine_peak']:.2f}%"])
table(['Phase','Rows','Flagged arm samples / total'],[[phase['name'],f"{case['rows']:,}",f"{sum(arm['load_flagged_samples'] for arm in case['arms'].values())} / 36"] for phase in d['phases'] for case in phase['cases']])
add('Per-arm/per-round external-CPU means, peaks, flags and telemetry coverage are retained in `summary.json` and the raw logs. No flagged sample is excluded. In particular, the primary 5M group is heavily load-affected and does not establish a precise gain or optimum.')
add(f'''The primary table has six internal arms: published default 16 MiB; equal-512
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

Current source is `{commit}`. The measured searchd SHA256 is
`{meta['binaries']['searchd']}`. All six affected translation units were
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
''')
(p/'ADAPTIVE_CACHE_2026-11-13.md').write_text('\n'.join(parts))
print('Wrote current adaptive report with default/adaptive QPS, CPU and memory tables.')
