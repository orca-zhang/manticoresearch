"""Journal validation and plotting shared with the independent M4 report."""
import json,statistics

def delta(before, after):
    return (after / before - 1) * 100


def validate(data, measurement):
    assert data['completed']
    total, flagged = 0, 0
    for case in data['cases']:
        rows = [json.loads(x) for x in (measurement / (case['case']['name'] + '-samples.jsonl')).read_text().splitlines()]
        assert len(rows) == 2 * data['rounds']
        assert case['lifecycle_passed']
        for label, arm in case['arms'].items():
            raw = [x['sample'] for x in rows if x['arm'] == label]
            assert len(raw) == len(arm['samples']) == data['rounds']
            for a, b in zip(raw, arm['samples']):
                assert all(b[k] == v for k, v in a.items())
                assert a['completed'] > 0 and a['elapsed_seconds'] >= data['seconds_per_arm']
                total += a['completed']
                flagged += b['quality_flag']
            for metric in ('qps', 'server_cpu_ms_per_query'):
                assert statistics.median(s[metric] for s in raw) == arm[metric + '_median']
        a, b = [case['arms'][x] for x in ('baseline', 'tls')]
        assert delta(a['qps_median'], b['qps_median']) == case['qps_change_percent']
        assert delta(a['server_cpu_ms_per_query_median'], b['server_cpu_ms_per_query_median']) == case['cpu_change_percent']
        if case['case'].get('aa'):
            assert a['binary'] == b['binary'] == 'searchd-baseline'
        else:
            assert (a['binary'], b['binary']) == ('searchd-baseline', 'searchd-tls')
    return total, flagged


def plot(primary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5))
    for cache, color, marker in ((16, '#2866a6', 'o'), (0, '#bd671d', 's')):
        selected = sorted((x for x in primary if x['case']['cache_mib'] == cache), key=lambda x: x['case']['rows'])
        for axis, key, paired, title in zip(axes, ('qps_change_percent', 'cpu_change_percent'),
                                            ('paired_qps_changes_percent', 'paired_cpu_changes_percent'),
                                            ('QPS change (higher is better)', 'Server CPU/query change (lower is better)')):
            xs = [x['case']['rows'] for x in selected]
            ys = [x[key] for x in selected]
            axis.plot(xs, ys, marker=marker, color=color,
                      label=f'{cache} MiB block cache' if cache else 'Block cache disabled')
            for x, y, row in zip(xs, ys, selected):
                axis.vlines(x, min(row[paired]), max(row[paired]), color=color, alpha=.55)
                peer = next(p[key] for p in primary
                            if p['case']['rows'] == x and p['case']['cache_mib'] != cache)
                offset = 9 if y >= peer else -16
                axis.annotate(f'{y:+.2f}%', (x, y), xytext=(0, offset),
                              textcoords='offset points', ha='center', fontsize=9, color=color)
            axis.set_title(title, fontsize=11)
            axis.set_xscale('log')
            axis.set_xticks([20000, 1000000, 10000000], ['20k', '1M', '10M'])
            axis.set_xlabel('Table rows (log scale)')
            axis.set_ylabel('TLS vs upstream (%)')
            axis.axhline(0, color='gray', linewidth=.8, linestyle='--')
            axis.grid(alpha=.18)
            axis.margins(x=.15, y=.22)
            axis.legend(fontsize=9)
    fig.suptitle('PR #5045 · Linux/x86-64 Intel N100 · reader TLS only', fontsize=12)
    fig.text(.5, .015, 'Co-resident services • 8 clients • 256 stored rows/query • 6 alternating rounds × 5 s/arm\nPoints: ratio of medians. Whiskers: min–max of the six paired changes; not confidence intervals.\nUneven external load: QPS differences do not establish an isolated TLS speedup.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .94))
    fig.savefig(output / 'reader-tls-independent.png', dpi=180)
    fig.savefig(output / 'reader-tls-independent.svg')
    plt.close(fig)
