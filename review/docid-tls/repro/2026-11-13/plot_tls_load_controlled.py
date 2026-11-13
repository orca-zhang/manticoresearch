#!/usr/bin/env python3
"""Render both fresh idle-gated TLS passes, with every paired-round range."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def paired_range(entry, metric):
    before, after = entry['arms']['reference'], entry['arms']['tls']
    values = [(b[metric] / a[metric] - 1) * 100 for a, b in zip(before['samples'], after['samples'])]
    assert len(values) == 6
    center = (after[metric + '_median'] / before[metric + '_median'] - 1) * 100
    assert min(values) <= center <= max(values)
    return center, center - min(values), max(values) - center


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    root = args.evidence / 'tls-latest-block'
    phases = [json.loads((root / f'load-controlled-{i}.json').read_text()) for i in (1, 2)]
    sizes = [20000, 100000, 500000, 1000000, 5000000]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8))
    fig.suptitle('Reader TLS: fresh reruns with idle gates and CPU telemetry', y=.98, fontsize=15)
    for i, (data, color, marker) in enumerate(zip(phases, ['tab:blue', 'tab:orange'], ['o', 'D']), 1):
        cells = {(e['case']['docs'], e['case']['cache']): e for e in data['cases']
                 if not any(e['case'].get(k) for k in ['count', 'aa', 'mixed'])}
        entries = [cells[(n, 16777216)] for n in sizes]
        for ax, metric in zip(axes, ['qps', 'server_cpu_ms_per_query']):
            values = [paired_range(e, metric) for e in entries]
            # Small horizontal offsets keep independently measured ranges visible.
            x = [n * (0.97 if i == 1 else 1.03) for n in sizes]
            ax.errorbar(x, [v[0] for v in values], yerr=[[v[1] for v in values], [v[2] for v in values]],
                        color=color, marker=marker, linestyle=':', capsize=3,
                        label=f'Pass {i}' + (' (reverse case/start order)' if i == 2 else ''))
    first_5m = next(e for e in phases[0]['cases'] if e['case']['name'] == 'rows5000000-cache16777216')
    axes[0].annotate('Load-affected 5M result;\nnot reproduced in pass 2',
                     xy=(5000000 * .97, first_5m['qps_change_percent']),
                     xytext=(.52, .83), textcoords='axes fraction', fontsize=8,
                     arrowprops={'arrowstyle': '->', 'color': 'tab:blue'}, color='tab:blue')
    for ax, title, ylabel in zip(axes, ['Default 16 MiB block cache: throughput', 'Default 16 MiB block cache: server CPU'],
                                ['TLS QPS change (%) - higher is better', 'TLS CPU/query change (%) - lower is better']):
        ax.axhline(0, color='gray', linewidth=.8)
        ax.set_xscale('log')
        ax.set_xticks(sizes)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda n, _: f'{n/1e6:g}M' if n >= 1e6 else f'{n/1e3:g}K'))
        ax.minorticks_off()
        ax.set(title=title, xlabel='Dataset rows (log scale)', ylabel=ylabel)
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', alpha=.2)
        ax.legend(frameon=False, fontsize=8)
    aa = [next(e for e in d['cases'] if e['case'].get('aa'))['qps_change_percent'] for d in phases]
    fig.text(.5, .02,
             'Latest shared shards / XXH3 in both arms; DocID and query-result caches off. 8 clients, 256 returned rows.\n'
             '6 alternating rounds x 5 seconds/arm; fresh servers per case. Ranges: paired-round min/max, not confidence intervals.\n'
             f'1M A/A QPS changes: {aa[0]:+.2f}% / {aa[1]:+.2f}%. All samples retained. Idle gates do not guarantee isolation during timing.\n'
             'CPU placement/frequency and external activity remain uncontrolled. Lines guide the eye; no universal optimum is inferred.',
             ha='center', fontsize=8.5)
    fig.tight_layout(rect=(0, .18, 1, .94))
    args.output.mkdir(parents=True, exist_ok=True)
    for ext in ['png', 'svg']:
        target = args.output / f'reader-tls-load-controlled.{ext}'
        fig.savefig(target, dpi=220, bbox_inches='tight', facecolor='white')
        if ext == 'svg':
            target.write_text('\n'.join(s.rstrip() for s in target.read_text().splitlines()) + '\n')
    plt.close(fig)
    print('Rendered both idle-gated TLS rerun passes.')


if __name__ == '__main__':
    main()
