from pathlib import Path
import json
root=Path('/private/tmp/manticore-block-cache-evidence-20261113/review/docid-tls')
e=Path('/private/tmp/manticore-vm-cache-review-20261113')
d=json.loads((e/'summary.json').read_text());initial,selected,main=d['phases'];commit=json.loads((e/'build-manifest.json').read_text())['source_commit']
comparisons=[c['comparisons']['default_to_adaptive16']['qps_change_percent'] for c in main['cases']]
best=max(main['cases'],key=lambda c:c['comparisons']['default_to_adaptive512']['qps_change_percent'])
mem=[t for t in main['transitions'] if t['arm']=='vm_adaptive512']
drops=[(t['phases'][0]['usage_after']['rss_bytes']-t['phases'][1]['usage_after']['rss_bytes'])/2**20 for t in mem]
nt=main['timed_arm_samples'];nd=main['diagnostic_samples'];nq=main['timed_queries'];dq=main['diagnostic_queries'];nf=main['load_flagged_samples']
def replace_intro(name,title,intro):
 p=root/name;s=p.read_text();marker='Updated review (2026-11-13):';assert marker in s
 p.write_text(title+'\n\n'+intro.strip()+'\n\n'+s[s.index(marker):])
replace_intro('PERFORMANCE.md','# Performance evidence and reporting boundaries',f'''## Current adaptive cache: default comparison and process-memory return

The [opt-in adaptive experiment](ADAPTIVE_CACHE_2026-11-13.md) uses system-mapped
decoded payloads, packed small-block regions and release of fully empty regions
to the OS. It remains outside both production PRs, with unchanged manual
16 MiB defaults and an explicit 512 MiB experimental entry ceiling.

The report gives absolute QPS and CPU/query for default 16 MiB versus current
adaptive 16/512 MiB at five sizes. Equal-16 QPS changes range from
{min(comparisons):+.2f}% to {max(comparisons):+.2f}% in the latest full rerun; this does not establish a
universal gain. The 512 MiB gain peaks at {best['comparisons']['default_to_adaptive512']['qps_change_percent']:+.2f}% for
{best['rows']:,} rows among these samples; this comparison also changes capacity.
All five sizes use fresh servers and six balanced ×5-second rounds. The
finite warmed
query pools do not constitute a cold full-table scan.

Two broad/hot/broad passes on the same 5M table observe process RSS drops of
{drops[0]:.2f} and {drops[1]:.2f} MiB from broad to hot. The report plots charged entries,
virtual mappings, RSS and physical footprint separately. Partial-region slack
and bounded empty spares remain; the entry ceiling is not an RSS cap. Idle
shards do not advance lookup-driven reclamation.

All {nt} timed arm samples and {nd} diagnostic stage samples remain,
including {nf} external-load flags. All five throughput cases and both memory
passes are newly measured; no earlier results are pooled into the tables. No adaptive-plus-TLS result
exists. Exact absolute values, negative results, controls and load limits are
in the report and CSV.

![Default and current adaptive throughput](figures/adaptive-cache-capacity.png)''')
replace_intro('VALIDATION.md','# Validation record',f'''## Current adaptive cache validation

The [adaptive report](ADAPTIVE_CACHE_2026-11-13.md) uses source
`{commit}`, based on #5042 `376fbf9`, with no reader TLS. It remains outside
both production PRs.

- Full native GoogleTests: **537/537 passed**.
- Focused native, ASan+UBSan and TSan: **19 tests ×20 each passed**.
- Coverage includes mapped-region packing/reuse/release, concurrency, pinned
  references, real stored-field cold-entry reclamation, uncompressed small/large
  fields, tiny-budget fallback and the 100k-row working set fitting 16 MiB.
- API smoke matches the updated metric golden. All {nt + nd} timed arm/stage
  response checks and post-timing SQL lifecycle checks pass: {nq:,} primary/repeat
  queries plus {dq:,} diagnostic queries.
- Every timed telemetry interval has full coverage. All {nf} primary/repeat
  load-flagged samples remain; flags are annotations, not exclusions. The latest
  full rerun contributes {main['timed_arm_samples']} samples with {main['load_flagged_samples']} flags.

All affected translation units were rebuilt; unchanged engine/dependency
objects were reused. Sanitizers instrument docstore, SkipCache, file I/O and
focused tests, not the entire engine. Custom mapped slots lack ordinary
per-allocation heap redzones. LeakSanitizer is unsupported on this macOS runtime
and ASan uses `detect_leaks=0`. Supported inherited stack-calibration overrides
are recorded; no fresh automatic calibration is claimed. Exact commands,
source snapshots, binary hashes and the plan are in
[evidence](evidence/2026-11-13/vm-cache/).

Observed process-memory return is specific to the recorded M4 Pro workload;
Linux/Windows runtime behavior, memory pressure, idle-timer reclamation,
SkipCache throughput and adaptive-plus-TLS are unmeasured. Upstream #5042 CI
was rechecked: run 43408089087 remains `action_required`, zero jobs, awaiting
maintainer fork-workflow approval. Experimental local test success does not
establish upstream CI success.''')
print('Updated current performance and validation summaries.')
