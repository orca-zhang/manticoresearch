#!/usr/bin/env python3
"""Plot capacity and adaptive-policy effects separately, including memory transitions."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def series(ax, entries, name, color, label, metric='qps_change_percent'):
    x = [e['rows'] for e in entries]
    values = [e['comparisons'][name] for e in entries]
    if metric == 'qps_change_percent':
        ax.vlines(x, [min(v['paired_qps_changes_percent']) for v in values],
                  [max(v['paired_qps_changes_percent']) for v in values], color=color, alpha=.5)
    ax.plot(x, [v[metric] for v in values], marker='o', color=color, label=label)


def style(ax, rows, title, ylabel, zero=False):
    ax.set_xscale('log')
    ax.set_xticks(rows)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda n, _: f'{n/1e6:g}M' if n >= 1e6 else f'{n/1e3:g}K'))
    ax.minorticks_off()
    ax.set(title=title, xlabel='Dataset rows (log scale)', ylabel=ylabel)
    if zero:
        ax.axhline(0, color='gray', linewidth=.8)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=.2)
    ax.legend(frameon=False, fontsize=8)


def save(fig, output, name, caption):
    fig.text(.5, .02, caption, ha='center', va='bottom', fontsize=8.5)
    fig.tight_layout(rect=(0, .18, 1, .93))
    for ext in ['png', 'svg']:
        target = output / f'{name}.{ext}'
        fig.savefig(target, dpi=200, bbox_inches='tight', facecolor='white')
        if ext == 'svg':
            target.write_text('\n'.join(line.rstrip() for line in target.read_text().splitlines()) + '\n')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads((args.evidence / 'summary.json').read_text())
    raw = json.loads((args.evidence / 'sql/matrix.json').read_text())
    entries = data['cases']
    rows = [e['rows'] for e in entries]
    args.output.mkdir(parents=True, exist_ok=True)
    common = ('M4 Pro / Clang 21 -O2; 8 clients, 256 returned rows; 128-byte text, 16 KiB / LZ4. No reader TLS.\n'
              'Native DocID and SQL query caches off. Six balanced rounds x 3 seconds/arm, with idle gates and CPU logs.\n'
              'QPS ranges are paired-round min/max, not confidence intervals. All samples retained; lines guide the eye.\n'
              'Both 16 and 512 MiB use 16 shards. Raising the ceiling and enabling adaptive reclamation are distinct changes.')
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    fig.suptitle('A larger decoded working set can benefit from a larger cache ceiling', fontsize=15)
    for label, color, caption, linestyle in [('off0', 'tab:gray', 'Cache off', '-'),
             ('manual16', 'tab:orange', 'Manual 16 MiB', '-'), ('manual512', 'tab:blue', 'Manual 512 MiB', '-'),
             ('adaptive512', 'tab:green', 'Adaptive, 512 MiB ceiling', '--')]:
        axes[0].plot(rows, [e['arms'][label]['qps_median'] for e in entries], color=color,
                     linestyle=linestyle, marker='o', label=caption)
    series(axes[1], entries, 'capacity16_to512', 'tab:blue', 'Manual 16 to 512 MiB')
    series(axes[1], entries, 'off_to_manual512', 'tab:orange', 'Off to manual 512 MiB')
    style(axes[0], rows, 'Absolute throughput', 'QPS (higher is better)')
    style(axes[1], rows, 'Capacity and cache-enable comparisons', 'QPS change (%)', True)
    save(fig, args.output, 'adaptive-cache-capacity', common)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    fig.suptitle('Adaptive policy at an equal 512 MiB ceiling: separate from capacity gains', fontsize=15)
    for name, color, label in [('adaptive512', 'tab:green', 'Manual to adaptive, 512 MiB'),
                              ('manual16_regression', 'tab:blue', 'Before/after, default manual 16 MiB'),
                              ('cache_off_control', 'tab:gray', 'Same binary, cache-off control')]:
        series(axes[0], entries, name, color, label)
        series(axes[1], entries, name, color, label, 'cpu_query_change_percent')
    style(axes[0], rows, 'Throughput changes', 'QPS change (%) - higher is better', True)
    style(axes[1], rows, 'Server CPU per query', 'CPU/query change (%) - lower is better', True)
    save(fig, args.output, 'adaptive-cache-policy', common)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    fig.suptitle('5M-row table: broad working set, smaller hot set, then broad again', fontsize=15)
    for entry in raw['transitions']:
        color = 'tab:green' if entry['arm'] == 'adaptive512' else 'tab:blue'
        phase_starts = [p['from_before_warmup'] for p in entry['phases']]
        phase_ends = phase_starts[1:] + [entry['phases'][-1]['sample']['to_monotonic_seconds']]
        points = []
        for sample in entry['memory_samples']:
            stamp = sample['monotonic_seconds']
            for i, (start, end) in enumerate(zip(phase_starts, phase_ends)):
                if start <= stamp <= end:
                    points.append((i + (stamp - start) / (end - start), sample))
                    break
        label = ('Adaptive' if entry['arm'] == 'adaptive512' else 'Manual') + f", pass {entry['pass_number']}"
        for ax, metric in zip(axes, ['cache_used_bytes', 'rss_bytes']):
            ax.plot([x for x, _ in points], [s[metric] / 2**20 for _, s in points], color=color,
                    linestyle='-' if entry['pass_number'] == 1 else '--', label=label)
    for ax, title in zip(axes, ['Charged cached blocks and LRU entries', 'Server process RSS']):
        ax.set(title=title, ylabel='MiB', xlabel='Workload phase (normalized progress within each phase)')
        ax.set_xticks([.5, 1.5, 2.5], ['5M ID range', '20K hot ID range', '5M range again'])
        for x in (1, 2):
            ax.axvline(x, color='gray', linewidth=.8, alpha=.6)
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', alpha=.2)
        ax.legend(frameon=False, fontsize=8)
    axes[0].axhline(512, color='gray', linestyle=':', linewidth=.8)
    save(fig, args.output, 'adaptive-cache-working-set',
         'Same candidate binary, manual/adaptive at a 512 MiB entry ceiling. Both already allocate on demand.\n'
         'Two fresh-server passes, reversed arm order; 8 seconds per stage after warmup. Memory probes every 0.2 seconds.\n'
         'Phase widths are normalized for comparison; raw elapsed times remain in JSON. Probes run during this diagnostic.\n'
         'The entry ceiling does not bound process RSS. Idle shards do not advance lookup-driven reclamation epochs.')
    print('Rendered adaptive capacity, policy and working-set figures.')


if __name__ == '__main__':
    main()
