#!/usr/bin/env python3
"""Plot original-cache and latest-cache TLS measurements (requires matplotlib)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def load(path):
    return json.loads(path.read_text())


def text_cells(data):
    return {(e['case']['docs'], e['case']['cache']): e for e in data['cases']
            if not any(e['case'].get(k) for k in ['count', 'aa', 'mixed']) and e['case']['batch'] == 256}


def span(entry):
    a, b = entry['arms']['reference']['samples'], entry['arms']['tls']['samples']
    assert len(a) == len(b) == 6
    values = [(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a, b)]
    mid = entry['qps_change_percent']
    assert min(values) <= mid <= max(values)
    return mid - min(values), max(values) - mid


def row_label(value, _=None):
    return f'{value / 1e6:g}M' if value >= 1e6 else f'{value / 1e3:g}K'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    old = text_cells(load(args.evidence / 'tls/scale-matrix.json'))
    latest = text_cells(load(args.evidence / 'tls-latest-block/matrix.json'))
    repeat = text_cells(load(args.evidence / 'tls-latest-block/repeat-default.json'))
    sizes = [20000, 100000, 500000, 1000000, 5000000]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 6))
    fig.suptitle('Reader TLS: original and latest block-cache baselines', fontsize=15, y=.98)
    for data, label, color, marker in [(old, 'Original single LRU / CRC32 (historical)', 'tab:gray', 'o'),
                                       (latest, 'Latest shards / XXH3: initial 3-second runs', 'tab:blue', 's')]:
        entries = [data[(n, 16777216)] for n in sizes]
        ranges = [span(e) for e in entries]
        axes[0].errorbar(sizes, [e['qps_change_percent'] for e in entries],
                         yerr=[[v[0] for v in ranges], [v[1] for v in ranges]],
                         color=color, marker=marker, linestyle=':', capsize=3, label=label)
    entries = [repeat[(n, 16777216)] for n in [20000, 1000000, 5000000]]
    ranges = [span(e) for e in entries]
    axes[0].errorbar([e['case']['docs'] for e in entries], [e['qps_change_percent'] for e in entries],
                     yerr=[[v[0] for v in ranges], [v[1] for v in ranges]],
                     marker='^', linestyle='none', markerfacecolor='white', color='tab:blue',
                     alpha=.6, markersize=8, capsize=3,
                     label='Latest cache: earlier unmonitored 5-second repeats')
    axes[0].axhline(0, color='gray', linewidth=.8)
    axes[0].set_xscale('log')
    axes[0].set_xticks(sizes)
    axes[0].xaxis.set_major_formatter(FuncFormatter(row_label))
    axes[0].minorticks_off()
    axes[0].set(title='TLS delta at the default 16 MiB block budget', xlabel='Dataset rows (log scale)', ylabel='TLS QPS change (%)')
    axes[0].legend(frameon=False, fontsize=8, loc='best')
    budgets = [0, 16777216, 134217728, 536870912]
    for arm, name, shift, color in [('reference', 'Latest block cache, reader map locked', -.18, 'tab:gray'),
                                   ('tls', 'Latest block cache, reader TLS', .18, 'tab:blue')]:
        axes[1].bar([i + shift for i in range(4)], [latest[(5000000, c)]['arms'][arm]['qps_median'] for c in budgets],
                    .34, color=color, label=name)
    axes[1].set(title='5M rows, latest cache: absolute throughput', xlabel='Block-cache budget (MiB)', ylabel='QPS (median)',
                xticks=list(range(4)), xticklabels=['0', '16', '128', '512'])
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
    fig.text(.5, .02, 'Each percentage compares TLS off/on with the SAME block-cache implementation in both arms.\n'
             'Two separately measured source contexts; do not interpret the gap between series as the block-cache speedup.\n'
             '8 clients, 256 rows/query. Bars on the left: six paired-round ranges, not confidence intervals. Lines guide the eye.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .15, 1, .94))
    args.output.mkdir(parents=True, exist_ok=True)
    for ext in ['png', 'svg']:
        target = args.output / f'reader-tls-cache-comparison.{ext}'
        fig.savefig(target, dpi=220, bbox_inches='tight', facecolor='white')
        if ext == 'svg':
            target.write_text('\n'.join(line.rstrip() for line in target.read_text().splitlines()) + '\n')
    plt.close(fig)
    print('Rendered original/latest block-cache comparison as PNG and SVG.')


if __name__ == '__main__':
    main()
