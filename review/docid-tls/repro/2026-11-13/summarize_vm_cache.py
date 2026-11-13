#!/usr/bin/env python3
"""Validate VM-cache evidence and derive default/adaptive QPS, CPU and memory tables."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

from summarize_cache_budgets import sample_load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    root = args.evidence
    manifest = json.loads((root / 'build-manifest.json').read_text())
    plan = json.loads((root / 'measurement-plan.json').read_text())
    idle_plan = json.loads((root / 'idle-repeat-plan.json').read_text())
    assert manifest['reader_tls'] is False
    assert plan['written_before_results'] and plan['reader_tls'] is False
    assert plan['source_commit'] == manifest['source_commit']
    assert plan['source_patch_sha256'] == manifest['source_patch_sha256']
    assert hashlib.sha256((root / 'vm-cache.patch').read_bytes()).hexdigest() == manifest['source_patch_sha256']
    for name, digest in manifest['sources'].items():
        assert hashlib.sha256((root / 'candidate-source' / name).read_bytes()).hexdigest() == digest
    assert idle_plan['written_before_results'] and idle_plan['source_commit'] == manifest['source_commit']
    resume_plan = json.loads((root / 'latest-resume-plan.json').read_text())
    memory_plan = json.loads((root / 'latest-memory-plan.json').read_text())
    assert resume_plan['written_before_resumed_results'] and memory_plan['written_before_diagnostic_results']
    assert resume_plan['source_commit'] == memory_plan['source_commit'] == manifest['source_commit']
    result = dict(phases=[], latest_phase='idle-repeat', all_completed_samples_retained=True)
    csv_rows = []
    for phase, sizes in [('matrix', 5), ('repeat', 2), ('idle-repeat', 5)]:
        data = json.loads((root / phase / 'matrix.json').read_text())
        assert data['completed'] and data['reader_tls'] is False
        assert data['rounds'] == 6 and data['docid_lookup_cache_size'] == data['qcache_max_bytes'] == 0
        assert len(data['cases']) == sizes
        expected_rows = idle_plan['rows'] if phase == 'idle-repeat' else plan['matrix_rows'] if phase == 'matrix' else plan['longer_repeats']['rows']
        assert [c['rows'] for c in data['cases']] == expected_rows
        assert data['seconds_per_arm'] == (idle_plan['seconds_per_arm'] if phase == 'idle-repeat' else plan['seconds_per_arm'] if phase == 'matrix' else plan['longer_repeats']['seconds_per_arm'])
        if phase == 'idle-repeat':
            assert data['binary_sha256'] == idle_plan['binary_sha256']
            assert hashlib.sha256(json.dumps(data['cases'][:4], sort_keys=True).encode()).hexdigest() == resume_plan['completed_cases_sha256']
        assert len(data['transitions']) == (0 if phase == 'repeat' else 4)
        assert data['binary_sha256']['candidate'] == manifest['binaries']['searchd']
        for name, digest in data['scripts_sha256'].items():
            assert hashlib.sha256((root / 'driver' / name).read_bytes()).hexdigest() == digest
        summary = dict(name=phase, seconds_per_arm=data['seconds_per_arm'], cases=[], transitions=[],
            timed_arm_samples=0, timed_queries=0, load_flagged_samples=0,
            diagnostic_samples=0, diagnostic_queries=0, diagnostic_load_flagged_samples=0)
        for entry in data['cases']:
            assert entry['lifecycle_checks_passed']
            assert set(entry['arms']) == set(entry['arm_configuration']) == set(plan['arms'])
            assert entry['idle_gate']['idle_percent_mean'] >= 90 and entry['idle_gate']['idle_percent_min'] >= 80
            telemetry = [json.loads(s) for s in (root / phase / f"matrix-{entry['rows']}-load.jsonl").read_text().splitlines()]
            case = dict(rows=entry['rows'], arms={}, comparisons=entry['comparisons'], idle_gate=entry['idle_gate'])
            journal = [json.loads(s) for s in (root / phase / f"matrix-{entry['rows']}-samples.jsonl").read_text().splitlines()]
            assert len(journal) == 36
            for row in journal:
                assert row['sample'] == entry['arms'][row['arm']]['samples'][row['sample']['round']]
            for name, arm in entry['arms'].items():
                samples = arm['samples']
                assert len(samples) == 6 and [s['round'] for s in samples] == list(range(6))
                for metric in ['qps', 'server_cpu_ms_per_query', 'rss_bytes', 'p95_ms']:
                    assert arm[metric + '_median'] == statistics.median(s[metric] for s in samples)
                config = entry['arm_configuration'][name]
                if config['binary'] != 'reference':
                    assert all(0 <= s['cache']['used_bytes'] <= config['cache_mib'] * 2**20 for s in samples)
                if config['binary'] == 'candidate':
                    assert all(0 <= s['cache']['spare_bytes'] <= 1024**2 and s['cache']['mapped_bytes'] >= s['cache']['spare_bytes'] for s in samples)
                loads = [sample_load(s, telemetry) for s in samples]
                case['arms'][name] = {k: v for k, v in arm.items() if k.endswith('_median')}
                case['arms'][name].update(sample_load=loads, load_flagged_samples=sum(s['elevated_external_load'] for s in loads),
                    cache_median={k: statistics.median(s['cache'][k] for s in samples) if samples[0]['cache'][k] is not None else None
                                  for k in ['used_bytes', 'mapped_bytes', 'spare_bytes']})
                summary['timed_arm_samples'] += 6
                summary['timed_queries'] += sum(s['completed'] for s in samples)
                summary['load_flagged_samples'] += sum(s['elevated_external_load'] for s in loads)
            for name, comp in case['comparisons'].items():
                a, b = (case['arms'][comp[k]] for k in ('before_arm', 'after_arm'))
                assert comp['qps_change_percent'] == (b['qps_median'] / a['qps_median'] - 1) * 100
                assert comp['cpu_query_change_percent'] == (b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100
                x, y = (entry['arms'][comp[k]]['samples'] for k in ('before_arm', 'after_arm'))
                assert comp['paired_qps_changes_percent'] == [(v['qps'] / u['qps'] - 1) * 100 for u, v in zip(x, y)]
                csv_rows.append(dict(phase=phase, rows=entry['rows'], comparison=name, before_qps=a['qps_median'], after_qps=b['qps_median'],
                    before_cpu_ms_query=a['server_cpu_ms_per_query_median'], after_cpu_ms_query=b['server_cpu_ms_per_query_median'],
                    qps_change_percent=comp['qps_change_percent'], cpu_query_change_percent=comp['cpu_query_change_percent'],
                    paired_qps_min_percent=min(comp['paired_qps_changes_percent']), paired_qps_max_percent=max(comp['paired_qps_changes_percent'])))
            summary['cases'].append(case)
        for entry in data['transitions']:
            assert entry['lifecycle_checks_passed'] and len(entry['phases']) == 3
            assert entry['idle_gate']['idle_percent_mean'] >= 90 and entry['idle_gate']['idle_percent_min'] >= 80
            assert [p['name'] for p in entry['phases']] == ['large', 'hot', 'large-again']
            for sample in entry['memory_samples']:
                assert 0 <= sample['cache']['used_bytes'] <= 512 * 2**20
                if entry['configuration']['binary'] == 'candidate':
                    assert 0 <= sample['cache']['spare_bytes'] <= 2**20
                    assert sample['cache']['mapped_bytes'] >= sample['cache']['spare_bytes']
            telemetry = [json.loads(s) for s in (root / phase / f"transition-{entry['pass_number']}-{entry['arm']}-load.jsonl").read_text().splitlines()]
            phases = []
            for p in entry['phases']:
                load = sample_load(dict(p['sample'], round=0), telemetry)
                phases.append(dict(p, load=load))
                summary['diagnostic_samples'] += 1
                summary['diagnostic_queries'] += p['sample']['completed']
                summary['diagnostic_load_flagged_samples'] += load['elevated_external_load']
            summary['transitions'].append(dict(pass_number=entry['pass_number'], arm=entry['arm'], phases=phases))
        assert summary['timed_arm_samples'] == sizes * 36
        assert summary['diagnostic_samples'] == (0 if phase == 'repeat' else 12)
        result['phases'].append(summary)
    (root / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    with (root / 'summary.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader(); writer.writerows(csv_rows)
    print(json.dumps([{k: v for k, v in p.items() if k not in ['cases', 'transitions']} for p in result['phases']], indent=2))


if __name__ == '__main__':
    main()
