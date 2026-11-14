#!/usr/bin/env python3
"""Validate retained measurements, export all samples, and plot final #5042 controls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

LABELS = {'off': 'Cache off', 'adaptive16': 'Adaptive 16 MiB (default)',
          'adaptive128': 'Adaptive 128 MiB',
          'manual512': 'Fixed 512 MiB (reference)', 'adaptive512': 'Adaptive 512 MiB'}
ORDER = list(LABELS)
MIB = 2**20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root, out = args.root, args.output
    out.mkdir(parents=True, exist_ok=True)
    primary = json.loads((root / 'measurement/results.json').read_text())
    assert primary['completed'] and primary['reader_tls'] is False
    assert primary['docid_cache_bytes'] == primary['query_cache_bytes'] == 0
    paths = [root / 'measurement/results.json', *sorted(root.glob('confirm-*/results.json')),
             root / 'controls/results.json']
    series, all_rows, memory_rows = [], [], []
    chosen = {c['name']: (paths[0].parent.name, c) for c in primary['cases']}
    for path in paths:
        data = json.loads(path.read_text())
        assert data['completed']
        assert data['binary_sha256'] == primary['binary_sha256']
        source = path.parent.name
        if source.startswith('confirm-'):
            for c in data['cases']:
                assert c['name'] in chosen
                assert any(s['quality_flag'] for a in chosen[c['name']][1]['arms'].values() for s in a['samples'])
                chosen[c['name']] = source, c
        for case in data['cases']:
            assert case['lifecycle_passed']
            journal = [json.loads(x) for x in (path.parent / (case['name']+'-samples.jsonl')).read_text().splitlines()]
            assert len(journal) == sum(len(a['samples']) for a in case['arms'].values())
            for label, arm in case['arms'].items():
                assert len(arm['samples']) == 6
                for key in ('qps', 'cpu_ms_per_query', 'rss_bytes', 'footprint_bytes', 'p95_ms'):
                    assert arm[key] == statistics.median(s[key] for s in arm['samples'])
                for s in arm['samples']:
                    raw = next(j['sample'] for j in journal if j['arm']==label and j['sample']['round']==s['round'])
                    assert all(s[k] == v for k, v in raw.items())
                    assert s['completed'] > 0 and s['qps'] > 0 and s['cpu_ms_per_query'] > 0
                    all_rows.append(dict(series=source, case=case['name'], rows=case['rows'], arm=label,
                        round=s['round']+1, qps=s['qps'], cpu_ms_per_query=s['cpu_ms_per_query'],
                        completed=s['completed'], elapsed_seconds=s['elapsed_seconds'],
                        p95_ms=s['p95_ms'], rss_bytes=s['rss_bytes'], footprint_bytes=s['footprint_bytes'],
                        used_bytes=s['cache']['used_bytes'], mapped_bytes=s['cache']['mapped_bytes'],
                        spare_bytes=s['cache']['spare_bytes'], quality_flag=s['quality_flag']))
        for m in data.get('memory', []):
            assert m['lifecycle_passed'] and len(m['stages'])==3
            for s in m['stages']:
                memory_rows.append(dict(pass_number=m['pass_number'], arm=m['arm'], stage=s['stage'],
                    used_mib=s['cache']['used_bytes']/MIB, mapped_mib=s['cache']['mapped_bytes']/MIB,
                    spare_mib=s['cache']['spare_bytes']/MIB, rss_mib=s['usage']['rss_bytes']/MIB,
                    footprint_mib=s['usage']['footprint_bytes']/MIB, quality_flag=s['quality_flag']))
        series.append(dict(path=str(path.relative_to(root)), data=data))
    def write_csv(name, rows):
        with (out / name).open('w', newline='') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    write_csv('all-samples.csv', all_rows)
    write_csv('memory-stages.csv', memory_rows)
    summary=[]
    selected=sorted(chosen.values(), key=lambda pair: pair[1]['rows'])
    for source,c in selected:
        off=c['arms']['off']
        for label in ORDER:
            a=c['arms'][label]
            summary.append(dict(rows=c['rows'],series=source,arm=label,qps=a['qps'],
                qps_over_off=a['qps']/off['qps'],cpu_ms_per_query=a['cpu_ms_per_query'],
                cpu_change_percent=(a['cpu_ms_per_query']/off['cpu_ms_per_query']-1)*100,
                used_mib=statistics.median(s['cache']['used_bytes'] for s in a['samples'])/MIB,
                mapped_mib=statistics.median(s['cache']['mapped_bytes'] for s in a['samples'])/MIB,
                rss_mib=a['rss_bytes']/MIB,footprint_mib=a['footprint_bytes']/MIB))
    write_csv('summary.csv',summary)
    (out/'summary.json').write_text(json.dumps(dict(source_commit=primary['source_commit'],
        binary_sha256=primary['binary_sha256'],primary=summary,memory=memory_rows,
        all_timed_samples=len(all_rows),all_checked_timed_queries=sum(s['completed'] for s in all_rows),
        all_flagged_samples=sum(s['quality_flag'] for s in all_rows),
        selected_flagged_samples=sum(s['quality_flag'] for _,c in selected for a in c['arms'].values() for s in a['samples']),
        selected_series={c['name']:source for source,c in selected}),indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.fonttype':'none'})
    fig,axes=plt.subplots(2,1,figsize=(10,8),sharex=True,layout='constrained')
    colors={'adaptive16':'#e69f00','adaptive128':'#009e73',
            'manual512':'#cc79a7','adaptive512':'#0072b2'}
    x=[c['rows'] for _,c in selected]
    for label in ORDER[1:]:
        for i,key in enumerate(('qps','cpu_ms_per_query')):
            y=[c['arms'][label][key]/c['arms']['off'][key] for _,c in selected]
            axes[i].plot(x,y,marker='o',linestyle='--' if label.startswith('manual') else '-',
                         color=colors[label],label=LABELS[label],linewidth=1.7)
    for ax in axes:
        ax.axhline(1,color='black',linewidth=1,alpha=.6)
        ax.set_xscale('log');ax.grid(alpha=.18)
    axes[0].set_ylabel('QPS / cache off (higher is better)')
    axes[0].set_title('One final binary: capacity extends the useful working-set range')
    axes[0].legend(ncol=2,fontsize=9)
    axes[1].set_ylabel('Server CPU/query / cache off (lower is better)')
    axes[1].set_xticks(x,['20k','100k','1M','5M','20M'])
    axes[1].set_xlabel('Table rows; deterministic random query pools, 256 returned rows')
    fig.savefig(out/'capacity.png',dpi=170);fig.savefig(out/'capacity.svg');plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,7),sharey=True,layout='constrained')
    for m in primary['memory']:
        ax=axes[m['pass_number']-1,0 if m['arm']=='manual512' else 1]
        samples=m['memory_samples'];begin=samples[0]['monotonic_seconds']
        times=[s['monotonic_seconds']-begin for s in samples]
        for label,section,key,color in [('Charged entries','cache','used_bytes','#009e73'),
                ('Mapped payloads','cache','mapped_bytes','#e69f00'),
                ('Process RSS','usage','rss_bytes','#0072b2'),
                ('Physical footprint','usage','footprint_bytes','#cc79a7')]:
            ax.plot(times,[s[section][key]/MIB for s in samples],label=label,color=color,linewidth=1.6)
        for stage in ('hot','broad-again'):
            first=next(s for s in samples if s['stage']==stage)['monotonic_seconds']-begin
            ax.axvline(first,color='black',alpha=.4,linestyle=':')
            ax.text(first+.3,ax.get_ylim()[1]*.95,'20k hot' if stage=='hot' else '5M broad',fontsize=8,va='top')
        ax.set_title(f"Pass {m['pass_number']}: {LABELS[m['arm']]}")
        ax.set_xlabel('Seconds since first memory sample');ax.grid(alpha=.18)
    axes[0,0].legend(fontsize=8,loc='lower left')
    for ax in axes[:,0]:ax.set_ylabel('MiB')
    fig.suptitle('Same 5M-row table: broad access → 20k hot rows → broad access again')
    fig.savefig(out/'memory.png',dpi=170);fig.savefig(out/'memory.svg');plt.close(fig)
    lines=['# Final adaptive cache measurement tables','',
           'All random-query columns use the same final binary. QPS multipliers use cache off in the same case; these are configuration comparisons, not full-PR speedups over upstream.','',
           '| Rows | Configuration | QPS | QPS / off | Server CPU ms/query | CPU vs off | Charged / mapped MiB |',
           '| ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for s in summary:
        lines.append(f"| {s['rows']:,} | {LABELS[s['arm']]} | {s['qps']:,.1f} | {s['qps_over_off']:.3f}× | {s['cpu_ms_per_query']:.4f} | {s['cpu_change_percent']:+.2f}% | {s['used_mib']:.1f} / {s['mapped_mib']:.1f} |")
    lines+=['','## Memory stage endpoints','','| Pass | Configuration | Access phase | Charged MiB | Mapped MiB | RSS MiB | Physical footprint MiB |','| ---: | --- | --- | ---: | ---: | ---: | ---: |']
    for m in memory_rows:
        lines.append(f"| {m['pass_number']} | {LABELS[m['arm']]} | {m['stage']} | {m['used_mib']:.1f} | {m['mapped_mib']:.1f} | {m['rss_mib']:.1f} | {m['footprint_mib']:.1f} |")
    lines+=['','## Independent controls','','| Workload | Configuration | QPS | Server CPU ms/query |','| --- | --- | ---: | ---: |']
    for item in series:
        if item['path'].startswith('controls/'):
            for c in item['data']['cases']:
                for label,a in c['arms'].items():
                    if label=='manual16': continue
                    lines.append(f"| {c['name']} | {LABELS.get(label,label)} | {a['qps']:,.1f} | {a['cpu_ms_per_query']:.4f} |")
    (out/'TABLES.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(json.loads((out/'summary.json').read_text()),indent=2))


if __name__=='__main__':main()
