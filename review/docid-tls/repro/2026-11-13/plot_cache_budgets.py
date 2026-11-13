#!/usr/bin/env python3
"""Plot distinct implementation, cache-enable and reader-TLS comparisons."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SIZES = [20000, 100000, 500000, 1000000, 5000000]
COLORS = {0: 'tab:gray', 8: 'tab:orange', 16: 'tab:blue'}


def text_cases(phase):
    entries = {e['case']['docs']: e for e in phase['cases'] if not e['case'].get('count') and not e['case'].get('aa')}
    assert set(entries) == set(SIZES)
    return [entries[n] for n in SIZES]


def comparison_series(ax, entries, kind, budget, label):
    values = [next(c for c in e['comparisons'] if c['comparison_kind'] == kind and c['block_mib'] == budget) for e in entries]
    centers = [v['qps_change_percent'] for v in values]
    # The ratio of medians need not lie inside the paired-round range.
    ax.vlines(SIZES, [v['paired_qps_min_percent'] for v in values],
              [v['paired_qps_max_percent'] for v in values], colors=COLORS[budget], alpha=.55, linewidth=1)
    ax.plot(SIZES, centers, marker='o', color=COLORS[budget], label=label)


def style(ax, title, ylabel, zero=False):
    if zero:
        ax.axhline(0, color='gray', linewidth=.8)
    ax.set_xscale('log')
    ax.set_xticks(SIZES)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda n, _: f'{n / 1e6:g}M' if n >= 1e6 else f'{n / 1e3:g}K'))
    ax.minorticks_off()
    ax.set(title=title, xlabel='Dataset rows (log scale)', ylabel=ylabel)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=.2)
    ax.legend(frameon=False, fontsize=9)


def save(fig, output, name, footer):
    fig.text(.5, .025, footer, ha='center', va='bottom', fontsize=8.5)
    fig.tight_layout(rect=(0, .20, 1, .93))
    for extension in ('png', 'svg'):
        path = output / f'{name}.{extension}'
        fig.savefig(path, dpi=200, bbox_inches='tight', facecolor='white')
        if extension == 'svg':
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.summary.read_text())
    initial, _, combined = data['phases']
    no_tls, tls = text_cases(initial), text_cases(combined)
    args.output.mkdir(parents=True, exist_ok=True)
    common = ('M4 Pro / Clang 21 -O2; 8 clients, 256 returned rows; 128-byte text, 16 KiB / LZ4. DocID and SQL query caches off.\n'
              'Six balanced rounds x 3 seconds/arm; one active arm at a time; pre-case idle gate and continuous CPU logging.\n'
              'Vertical lines: paired-round min/max, not confidence intervals. All samples retained; lines guide the eye.\n'
              '8 MiB uses 8 shards; 16 MiB uses 16. Capacity and locking parallelism both change; no universal optimum is established.')
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.1))
    fig.suptitle('Latest shared block cache, without reader TLS: when does enabling it help?', fontsize=15)
    for budget in (0, 8, 16):
        axes[0].plot(SIZES, [e['arms'][f'candidate{budget}']['qps_median'] for e in no_tls],
                     color=COLORS[budget], marker='o', label='Cache off' if budget == 0 else f'{budget} MiB')
    for budget in (8, 16):
        comparison_series(axes[1], no_tls, 'candidate-cache-enable', budget, f'0 to {budget} MiB')
    style(axes[0], 'Same final binary: absolute throughput', 'QPS (higher is better)')
    style(axes[1], 'Same final binary: cache off to on', 'QPS change (%)', zero=True)
    gain_100k = next(c['qps_change_percent'] for e in no_tls if e['case']['docs'] == 100000
                     for c in e['comparisons'] if c['comparison_kind'] == 'candidate-cache-enable' and c['block_mib'] == 16)
    axes[1].annotate('100K: 8 MiB is slower;\n16 MiB is faster than off', xy=(100000, gain_100k),
                     xytext=(.4, .74), textcoords='axes fraction', fontsize=8,
                     arrowprops={'arrowstyle': '->'})
    save(fig, args.output, 'block-cache-budgets-off-on', common)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.1))
    fig.suptitle('Old single-LRU / CRC32 to shared shards / XXH3: a different denominator', fontsize=15)
    for budget in (0, 8, 16):
        comparison_series(axes[0], no_tls, 'old-to-new', budget, f'{budget} MiB in both arms')
    for budget in (8, 16):
        axes[1].plot(SIZES, [e['arms'][f'baseline{budget}']['qps_median'] for e in no_tls],
                     color=COLORS[budget], linestyle='--', marker='x', label=f'Old, {budget} MiB')
        axes[1].plot(SIZES, [e['arms'][f'candidate{budget}']['qps_median'] for e in no_tls],
                     color=COLORS[budget], marker='o', label=f'New, {budget} MiB')
    style(axes[0], 'Implementation change at equal cache budget', 'QPS change (%)', zero=True)
    style(axes[1], 'Old and new implementations: absolute throughput', 'QPS (higher is better)')
    save(fig, args.output, 'block-cache-budgets-implementation', common)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.1))
    fig.suptitle('Reader TLS on the latest shared block cache: separate paired measurements', fontsize=15)
    for budget in (0, 8, 16):
        comparison_series(axes[0], tls, 'tls-off-on', budget, f'{budget} MiB in both arms')
    for budget in (8, 16):
        comparison_series(axes[1], tls, 'candidate-cache-enable', budget, f'TLS on: 0 to {budget} MiB')
    style(axes[0], 'TLS off to on, at equal block-cache budget', 'QPS change (%)', zero=True)
    style(axes[1], 'Same TLS-on binary: block cache off to on', 'QPS change (%)', zero=True)
    save(fig, args.output, 'reader-tls-block-cache-budgets', common)
    print('Rendered three budget figures as PNG and SVG.')


if __name__ == '__main__':
    main()
