#!/usr/bin/env python3
"""Validate and summarize the paired block-cache budget and reader-TLS matrices."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import statistics


def sample_load(sample, telemetry):
    start, end = (sample[k] for k in ('from_monotonic_seconds', 'to_monotonic_seconds'))
    matched = [(s, max(0, min(end, s['monotonic_seconds']) -
                         max(start, s['monotonic_seconds'] - s['interval_seconds']))) for s in telemetry]
    matched = [(s, weight) for s, weight in matched if weight > 0]
    duration = sum(weight for _, weight in matched)
    assert duration > 0
    mean = sum(s['external_cpu_percent_machine'] * weight for s, weight in matched) / duration
    peak = max(s['external_cpu_percent_machine'] for s, _ in matched)
    coverage = duration / (end - start)
    assert abs(coverage - 1) < 1e-6, coverage
    return dict(round=sample['round'], external_cpu_percent_machine_mean=mean,
                external_cpu_percent_machine_peak=peak, coverage_fraction=coverage,
                elevated_external_load=mean > 10 or peak > 20)


def selfcheck():
    sample = dict(from_monotonic_seconds=1.5, to_monotonic_seconds=3.5, round=0)
    telemetry = [dict(monotonic_seconds=i, interval_seconds=1,
                      external_cpu_percent_machine=n) for i, n in [(2, 0), (3, 10), (4, 30)]]
    result = sample_load(sample, telemetry)
    assert result['coverage_fraction'] == 1 and result['external_cpu_percent_machine_mean'] == 12.5
    assert result['elevated_external_load'] and result['external_cpu_percent_machine_peak'] == 30
    print('Budget-summary overlap weighting and load-flag selfcheck passed.')


def summarize(evidence):
    phases, rows, pools, fixtures = [], [], {}, {}
    specs = [('block-cache-budgets', 'matrix', 'old-to-new'),
             ('block-cache-budgets', 'repeat', 'old-to-new'),
             ('tls-block-cache-budgets', 'matrix', 'tls-off-on')]
    for folder, name, kind in specs:
        root = evidence / folder
        data = json.loads((root / f'{name}.json').read_text())
        assert data['completed'] and data['rounds'] == 6
        assert len(data['cases']) == (2 if name == 'repeat' else 7)
        assert data['docid_lookup_cache_size'] == data['qcache_max_bytes'] == 0
        assert data['reader_buffer_budget_bytes'] == 8 * 2**20
        assert data['reader_tls'] == (False if kind == 'old-to-new' else {'baseline': False, 'candidate': True})
        for filename, digest in data['scripts_sha256'].items():
            assert hashlib.sha256((root / 'driver' / filename).read_bytes()).hexdigest() == digest
        if 'entry_script' in data:
            assert hashlib.sha256((root / 'driver' / data['entry_script']).read_bytes()).hexdigest() == data['entry_script_sha256']
        for count, info in data['fixtures'].items():
            assert fixtures.setdefault(count, info) == info
        phase = dict(name=f'{folder}/{name}', comparison_kind=kind, seconds_per_arm=data['seconds_per_arm'],
                     source_commits={k: v for k, v in data.items() if 'commit' in k}, binaries=data['binaries'],
                     calibration=data['calibration'], cases=[])
        for entry in data['cases']:
            case, control = entry['case'], entry['load_control']
            assert entry['lifecycle_checks_passed']
            assert control['idle_gate']['idle_percent_mean'] >= 90 and control['idle_gate']['idle_percent_min'] >= 80
            key = (case['docs'], bool(case.get('count')))
            assert pools.setdefault(key, entry['query_set_sha256']) == entry['query_set_sha256']
            telemetry = [json.loads(line) for line in (root / control['telemetry']).read_text().splitlines()]
            result = dict(case=case, query_set_sha256=entry['query_set_sha256'], arms={}, idle_gate=control['idle_gate'])
            for label, arm in entry['arms'].items():
                assert arm['docid_cache_used_bytes'] == 0 and len(arm['samples']) == 6
                assert [s['round'] for s in arm['samples']] == list(range(6))
                assert all(s['completed'] > 0 for s in arm['samples'])
                for metric in ['qps', 'server_cpu_ms_per_query', 'rss_bytes', 'p95_ms']:
                    assert arm[metric + '_median'] == statistics.median(s[metric] for s in arm['samples'])
                loads = [sample_load(s, telemetry) for s in arm['samples']]
                result['arms'][label] = {k: v for k, v in arm.items() if k.endswith('_median')}
                result['arms'][label].update(
                    timed_queries=sum(s['completed'] for s in arm['samples']), sample_load=loads,
                    external_cpu_percent_machine_median=statistics.median(s['external_cpu_percent_machine_mean'] for s in loads),
                    elevated_samples=sum(s['elevated_external_load'] for s in loads))
            groups = [('aa', {'8': entry['aa_comparison']})] if case.get('aa') else [
                (kind, entry['implementation_comparisons']), ('candidate-cache-enable', entry['candidate_cache_comparisons'])]
            result['comparisons'] = []
            for comparison_kind, comparisons in groups:
                for budget, comparison in comparisons.items():
                    a, b = (entry['arms'][comparison[k]] for k in ('before_arm', 'after_arm'))
                    qps = (b['qps_median'] / a['qps_median'] - 1) * 100
                    cpu = (b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100
                    paired = [(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a['samples'], b['samples'])]
                    assert qps == comparison['qps_change_percent'] and cpu == comparison['server_cpu_change_percent']
                    assert paired == comparison['paired_qps_changes_percent']
                    record = dict(phase=phase['name'], case=case['name'], rows=case['docs'],
                                  control='aa' if case.get('aa') else 'count' if case.get('count') else 'text',
                                  comparison_kind=comparison_kind, block_mib=int(budget), **comparison,
                                  before_qps=a['qps_median'], after_qps=b['qps_median'],
                                  before_cpu_ms_per_query=a['server_cpu_ms_per_query_median'],
                                  after_cpu_ms_per_query=b['server_cpu_ms_per_query_median'],
                                  before_rss_mib=a['rss_bytes_median'] / 2**20, after_rss_mib=b['rss_bytes_median'] / 2**20,
                                  paired_qps_min_percent=min(paired), paired_qps_max_percent=max(paired))
                    result['comparisons'].append(record)
                    rows.append({k: v for k, v in record.items() if k != 'paired_qps_changes_percent'})
            phase['cases'].append(result)
        phases.append(phase)
    samples = [s for phase in phases for entry in phase['cases'] for arm in entry['arms'].values() for s in arm['sample_load']]
    return dict(phases=phases, fixtures=fixtures, comparison_count=len(rows), timed_arm_samples=len(samples),
                timed_queries=sum(a['timed_queries'] for p in phases for e in p['cases'] for a in e['arms'].values()),
                elevated_samples=sum(s['elevated_external_load'] for s in samples),
                minimum_telemetry_coverage=min(s['coverage_fraction'] for s in samples),
                maximum_telemetry_coverage=max(s['coverage_fraction'] for s in samples),
                lowest_precase_mean_idle_percent=min(e['idle_gate']['idle_percent_mean'] for p in phases for e in p['cases']),
                sample_rejection='None; all completed samples retained; load flags are annotations.'), rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--selfcheck', action='store_true')
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.evidence and args.output
    summary, rows = summarize(args.evidence)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (args.output / 'summary.csv').write_text(stream.getvalue())
    print(json.dumps({k: v for k, v in summary.items() if k not in ('phases', 'fixtures')}, indent=2))


if __name__ == '__main__':
    main()
