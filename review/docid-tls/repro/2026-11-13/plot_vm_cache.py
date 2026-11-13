#!/usr/bin/env python3
"""Plot the current adaptive cache against defaults and show mapped-memory return."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def style(ax, rows, title, ylabel):
    ax.set_xscale('log'); ax.set_xticks(rows)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda n, _: f'{n/1e6:g}M' if n >= 1e6 else f'{n/1e3:g}K'))
    ax.minorticks_off(); ax.set(title=title, xlabel='Dataset rows (log scale)', ylabel=ylabel)
    ax.spines[['top', 'right']].set_visible(False); ax.grid(axis='y', alpha=.2)
    ax.legend(frameon=False, fontsize=8)


def save(fig, output, name, caption):
    fig.text(.5, .02, caption, ha='center', va='bottom', fontsize=8.5)
    fig.tight_layout(rect=(0, .17, 1, .93))
    for ext in ['png', 'svg']:
        p = output / f'{name}.{ext}'
        fig.savefig(p, dpi=200, bbox_inches='tight', facecolor='white')
        if ext == 'svg': p.write_text('\n'.join(s.rstrip() for s in p.read_text().splitlines()) + '\n')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    d = json.loads((args.evidence / 'summary.json').read_text())
    raw = json.loads((args.evidence / 'matrix/matrix.json').read_text())
    primary, repeat = d['phases']
    cases = primary['cases']; rows = [c['rows'] for c in cases]
    args.output.mkdir(parents=True, exist_ok=True)
    common = ('M4 Pro / Clang 21 -O2; 8 clients, 256 returned rows; 128-byte text, 16 KiB / LZ4. No reader TLS.\n'
              'DocID and SQL query caches off. Six balanced rounds: primary 3 s/arm; fresh-server repeats 5 s/arm.\n'
              f"Load flags: {primary['load_flagged_samples']}/{primary['timed_arm_samples']} primary, {repeat['load_flagged_samples']}/{repeat['timed_arm_samples']} repeat samples; all retained. Ranges are paired min/max, not confidence intervals.\n"
              'Equal 16 MiB compares implementations/modes; 16 to 512 MiB also changes capacity. Small blocks use 256-byte classes; backing slack is additional.')
    fig, ax = plt.subplots(1, 2, figsize=(13, 6));fig.suptitle('Current adaptive cache: throughput versus dataset size', fontsize=15)
    for name, color, label in [('default16','tab:gray','Default manual 16 MiB'),('vm_adaptive16','tab:orange','Adaptive 16 MiB'),('vm_adaptive512','tab:green','Adaptive 512 MiB ceiling')]:
        ax[0].plot(rows,[c['arms'][name]['qps_median'] for c in cases],marker='o',color=color,label=label)
    for name, color, label in [('default_to_adaptive16','tab:orange','Default to adaptive, equal 16 MiB'),('default_to_adaptive512','tab:green','Default 16 to adaptive 512 MiB')]:
        values=[c['comparisons'][name] for c in cases]
        ax[1].vlines(rows,[min(v['paired_qps_changes_percent']) for v in values],[max(v['paired_qps_changes_percent']) for v in values],color=color,alpha=.5)
        ax[1].plot(rows,[v['qps_change_percent'] for v in values],marker='o',color=color,label=label)
    peak=max(cases,key=lambda c:c['comparisons']['default_to_adaptive512']['qps_change_percent'])
    ax[1].annotate(f"Largest sampled gain\n{peak['rows']:,} rows",
        xy=(peak['rows'],peak['comparisons']['default_to_adaptive512']['qps_change_percent']),
        xytext=(10,15),textcoords='offset points',fontsize=8,
        arrowprops=dict(arrowstyle='-',color='tab:green'))
    ax[1].axhline(0,color='gray',linewidth=.8)
    style(ax[0],rows,'Absolute throughput','QPS (higher is better)');style(ax[1],rows,'Change relative to default 16 MiB','QPS change (%)')
    save(fig,args.output,'adaptive-cache-capacity',common)

    fig,ax=plt.subplots(1,2,figsize=(13,6));fig.suptitle('Current adaptive cache: server CPU per query and longer checks',fontsize=15)
    for name,color,label in [('default16','tab:gray','Default manual 16 MiB'),('vm_adaptive16','tab:orange','Adaptive 16 MiB'),('vm_adaptive512','tab:green','Adaptive 512 MiB ceiling')]:
        ax[0].plot(rows,[c['arms'][name]['server_cpu_ms_per_query_median'] for c in cases],marker='o',color=color,label=label)
    style(ax[0],rows,'Absolute server CPU per completed query','CPU milliseconds/query (lower is better)')
    for phase,marker,linestyle in [(primary,'o','-'),(repeat,'s','--')]:
        cells=phase['cases'];x=[c['rows'] for c in cells];values=[c['comparisons']['default_to_adaptive16'] for c in cells]
        label='Initial, 3 s/arm' if phase is primary else 'Fresh-server repeat, 5 s/arm'
        ax[1].vlines(x,[min(v['paired_qps_changes_percent']) for v in values],[max(v['paired_qps_changes_percent']) for v in values],alpha=.5)
        ax[1].plot(x,[v['qps_change_percent'] for v in values],marker=marker,linestyle=linestyle,label=label)
    ax[1].axhline(0,color='gray',linewidth=.8)
    style(ax[1],rows,'Default to adaptive at equal 16 MiB','QPS change (%)')
    save(fig,args.output,'adaptive-cache-policy',common)

    fig,axes=plt.subplots(1,2,figsize=(13,6));fig.suptitle('Adaptive 512 MiB: cached entries, live mappings and process memory',fontsize=15)
    for ax,entry in zip(axes,[t for t in raw['transitions'] if t['arm']=='vm_adaptive512']):
        starts=[p['from_before_warmup'] for p in entry['phases']];ends=starts[1:]+[entry['phases'][-1]['sample']['to_monotonic_seconds']]
        points=[]
        for sample in entry['memory_samples']:
            stamp=sample['monotonic_seconds']
            for i,(start,end) in enumerate(zip(starts,ends)):
                if start<=stamp<=end:
                    points.append((i+(stamp-start)/(end-start),sample));break
        for metric,color,label in [('used_bytes','tab:orange','Charged entries'),('mapped_bytes','tab:blue','All pool mappings'),('rss_bytes','tab:green','Process RSS'),('footprint_bytes','tab:purple','Physical footprint')]:
            values=[s['cache'][metric] if metric in s['cache'] else s[metric] for _,s in points]
            ax.plot([x for x,_ in points],[v/2**20 for v in values],color=color,label=label)
        for x in [1,2]:ax.axvline(x,color='gray',linewidth=.8,alpha=.6)
        ax.set(title=f"Fresh server, pass {entry['pass_number']}",ylabel='MiB',xlabel='Workload phase (normalized progress)')
        ax.set_xticks([.5,1.5,2.5],['5M ID range','20K hot prefix','5M range again'])
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,fontsize=8)
    save(fig,args.output,'adaptive-cache-working-set',
         'Same 5M-row table; fresh servers in two reversed-order diagnostic passes; 8 timed seconds/stage after warmup.\n'
         'Concurrent status/RSS/footprint probes every 0.2 s; phase widths are normalized, with raw timestamps archived.\n'
         'Pool payloads use system mappings; each shard retains at most one completely empty 64 KiB region (1 MiB for 16 shards).\n'
         'The entry ceiling excludes partial-region slack, spares, in-flight payloads and other engine memory. Diagnostic QPS is not primary evidence.')
    print('Rendered current adaptive throughput, CPU and process-memory figures.')


if __name__=='__main__': main()
