#!/usr/bin/env python3
"""Render the published figures from raw measurements (requires matplotlib)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def load(path):
    return json.loads(path.read_text())


def rows_label(value, _=None):
    return f'{value / 1e6:g}M' if value >= 1e6 else f'{value / 1e3:g}K'


def paired_span(entry):
    a, b = entry['arms']['reference']['samples'], entry['arms']['tls']['samples']
    assert len(a) == len(b) == 6
    changes = [(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a, b)]
    mid = entry['qps_change_percent']
    assert min(changes) <= mid <= max(changes)
    return mid - min(changes), max(changes) - mid


def style(ax):
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=.2)
    ax.set_axisbelow(True)


def save(fig, output, name):
    for ext in ('svg', 'png'):
        path = output / f'{name}.{ext}'
        fig.savefig(path, dpi=220, bbox_inches='tight', facecolor='white')
        if ext == 'svg':
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path,
                        help='evidence/2026-11-13 directory containing block-cache/ and tls/')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.evidence / 'block-cache'
    disabled = load(root / 'compare-docid0.json')['cases']
    extra = load(root / 'compare-extra-docid0.json')['cases']
    enabled = load(root / 'compare-docid128m.json')['cases']
    selected = lambda records: sorted(
        [e for e in records if e['case']['name'].endswith('default')],
        key=lambda e: e['case']['docs'])
    by_budget = [(selected(disabled + extra), 'DocID budget 0 (default)', 'tab:blue', 'o'),
                 (selected(enabled), 'DocID budget 128 MiB', 'tab:green', 's')]
    assert [e['case']['docs'] for e in by_budget[0][0]] == [20000, 100000, 500000, 1000000, 5000000]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 6.0))
    fig.suptitle('Shared block cache: measured sweet spot by dataset size', fontsize=15, y=.98)
    for records, label, color, marker in by_budget:
        xs = [e['case']['docs'] for e in records]
        ys = [e['qps_change_percent'] for e in records]
        ranges = [paired_span(e) for e in records]
        axes[0].errorbar(xs, ys, yerr=[[v[0] for v in ranges], [v[1] for v in ranges]],
                         label=label, color=color, marker=marker, linestyle=':', capsize=3)
        for arm, name, line, alpha in [('reference', 'Original cache', '--', .55),
                                       ('tls', 'Sharded + XXH3', '-', 1)]:
            axes[1].plot(xs, [e['arms'][arm]['qps_median'] for e in records],
                         marker=marker, linestyle=line, color=color, alpha=alpha,
                         label=f'{name}, DocID {"0" if color == "tab:blue" else "128 MiB"}')
    records = by_budget[0][0]
    peak = max(records, key=lambda e: e['qps_change_percent'])
    axes[0].annotate(f"Highest sampled uplift with DocID off:\n{rows_label(peak['case']['docs'])} rows, +{peak['qps_change_percent']:.1f}%",
                     xy=(peak['case']['docs'], peak['qps_change_percent']),
                     xytext=(32, -52), textcoords='offset points', fontsize=9,
                     arrowprops={'arrowstyle': '->', 'color': 'tab:blue'})
    axes[0].set(title='QPS gain over the original shared cache', ylabel='QPS change (%)')
    axes[0].axhline(0, color='gray', linewidth=.8)
    axes[1].set(title='Absolute throughput at the same 16 MiB block budget', ylabel='QPS (median)')
    for ax in axes:
        ax.set_xscale('log')
        ax.set_xticks([20000, 100000, 500000, 1000000, 5000000])
        ax.xaxis.set_major_formatter(FuncFormatter(rows_label))
        ax.minorticks_off()
        ax.set_xlabel('Dataset rows (log scale)')
        style(ax)
        ax.legend(fontsize=8, frameon=False, loc='best')
    fig.text(.5, .02, 'No reader TLS in either arm | 16 MiB block cache | 8 clients | 256 returned rows | Clang 21 -O2\n'
             'Points: ratio of arm medians. Bars: range of six paired-round changes, not confidence intervals.\n'
             '500K is a supplemental run. Lines guide the eye; no optimum between sampled sizes is inferred.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .15, 1, .94))
    save(fig, args.output, 'block-cache-size-sweet-spot')

    big = [next(e for e in disabled if e['case']['name'] == n) for n in ['5m-default', '5m-512m']]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 5.0))
    fig.suptitle('5M rows: cache budget and memory trade-off (DocID budget 0, no TLS)', fontsize=13)
    for arm, name, shift, color in [('reference', 'Original cache', -.18, 'tab:gray'),
                                    ('tls', 'Sharded + XXH3', .18, 'tab:blue')]:
        x = [i + shift for i in range(2)]
        qps = [e['arms'][arm]['qps_median'] for e in big]
        rss = [e['arms'][arm]['rss_bytes_median'] / 2**20 for e in big]
        axes[0].bar(x, qps, .34, label=name, color=color)
        axes[1].bar(x, rss, .34, label=name, color=color)
    for ax, title, ylabel in zip(axes, ['SQL throughput', 'Observed server memory'], ['QPS (median)', 'RSS MiB (median)']):
        ax.set(title=title, ylabel=ylabel, xlabel='Block-cache budget (MiB)', xticks=[0, 1], xticklabels=['16', '512'])
        style(ax)
        ax.legend(frameon=False, fontsize=8)
    for i, e in enumerate(big):
        axes[0].annotate(f"+{e['qps_change_percent']:.1f}%", (i, max(e['arms'][a]['qps_median'] for a in ['reference', 'tls'])),
                         xytext=(0, 5), textcoords='offset points', ha='center', fontsize=9)
    axes[0].set_ylim(0, max(e['arms']['tls']['qps_median'] for e in big) * 1.2)
    fig.text(.5, .02, 'Larger relative uplift at 16 MiB; higher absolute throughput at 512 MiB, with higher RSS.\n'
             'Only the shown budgets were sampled in this no-TLS comparison; no global budget optimum is claimed.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .15, 1, .94))
    save(fig, args.output, 'block-cache-budget-tradeoff')

    tls = load(args.evidence / 'tls/scale-summary.json')['cases']
    default = sorted([e for e in tls if e['control'] == 'text' and e['block_cache_mib'] == 16], key=lambda e: e['docs'])
    five = sorted([e for e in tls if e['control'] == 'text' and e['docs'] == 5000000], key=lambda e: e['block_cache_mib'])
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.4))
    fig.suptitle('Reader TLS only: dataset size and cache budget', fontsize=14)
    axes[0].plot([e['docs'] for e in default], [e['qps_change_percent'] for e in default], 'o:', color='tab:purple')
    axes[0].axhline(0, color='gray', linewidth=.8)
    axes[0].set_xscale('log')
    axes[0].set_xticks([e['docs'] for e in default])
    axes[0].xaxis.set_major_formatter(FuncFormatter(rows_label))
    axes[0].minorticks_off()
    axes[0].set(title='Default 16 MiB: no clear size-dependent gain', xlabel='Dataset rows (log scale)', ylabel='TLS QPS change (%)', ylim=(-3, 3))
    for arm, label, color, shift in [('reference_qps', 'Upstream before TLS', 'tab:gray', -.18), ('tls_qps', 'TLS only', 'tab:purple', .18)]:
        axes[1].bar([i + shift for i in range(len(five))], [e[arm] for e in five], .34, label=label, color=color)
    axes[1].set(title='5M rows: cache budget changes absolute throughput', xlabel='Block-cache budget (MiB)', ylabel='QPS (median)',
                xticks=list(range(len(five))), xticklabels=[str(e['block_cache_mib']) for e in five])
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes: style(ax)
    fig.text(.5, .02, 'Upstream vs TLS only, no native DocID cache or block-cache sharding | 8 clients | 256 rows/query\n'
             'Six alternating 3-second rounds. Ratios of medians; no confidence interval. All controls/negative cases remain in the report.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .15, 1, .94))
    save(fig, args.output, 'reader-tls-size-sweep')
    print('Wrote three figures as PNG and SVG; inputs are raw published measurements.')


if __name__ == '__main__':
    main()
