#!/usr/bin/env python3
"""Validate adaptive-cache raw samples and derive QPS, memory and load tables."""
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
    data = json.loads((root / 'sql/matrix.json').read_text())
    assert data['completed'] and data['reader_tls'] is False
    assert data['docid_lookup_cache_size'] == data['qcache_max_bytes'] == 0
    assert len(data['cases']) == 5 and len(data['transitions']) == 4
    for name, digest in data['scripts_sha256'].items():
        assert hashlib.sha256((root / 'driver' / name).read_bytes()).hexdigest() == digest
    manifest = json.loads((root / 'build-manifest.json').read_text())
    assert manifest['binaries']['searchd'] == data['binary_sha256']['candidate']
    assert hashlib.sha256((root / 'adaptive-cache.patch').read_bytes()).hexdigest() == manifest['source_patch_sha256']
    for name, digest in manifest['sources'].items():
        assert hashlib.sha256((root / 'candidate-source' / name).read_bytes()).hexdigest() == digest
    result = dict(cases=[], transitions=[], all_completed_samples_retained=True,
                  primary_timed_arm_samples=0, primary_timed_queries=0, primary_load_flagged_samples=0,
                  diagnostic_timed_arm_samples=0, diagnostic_timed_queries=0, diagnostic_load_flagged_samples=0)
    csv_rows = []
    for entry in data['cases']:
        assert entry['lifecycle_checks_passed']
        assert entry['idle_gate']['idle_percent_mean'] >= 90 and entry['idle_gate']['idle_percent_min'] >= 80
        telemetry = [json.loads(line) for line in (root / f"sql/matrix-{entry['rows']}-load.jsonl").read_text().splitlines()]
        case = dict(rows=entry['rows'], arms={}, comparisons=entry['comparisons'], idle_gate=entry['idle_gate'])
        for label, arm in entry['arms'].items():
            samples = arm['samples']
            assert len(samples) == 6 and [s['round'] for s in samples] == list(range(6))
            for metric in ['qps', 'server_cpu_ms_per_query', 'rss_bytes', 'p95_ms']:
                assert arm[metric + '_median'] == statistics.median(s[metric] for s in samples)
            cap = entry['arm_configuration'][label]['cache_mib'] * 2**20
            assert all(s['cache_used_bytes'] is None if label == 'reference16' else 0 <= s['cache_used_bytes'] <= cap for s in samples)
            loads = [sample_load(s, telemetry) for s in samples]
            case['arms'][label] = {k: v for k, v in arm.items() if k.endswith('_median')}
            case['arms'][label].update(sample_load=loads,
                cache_used_bytes_median=statistics.median(s['cache_used_bytes'] for s in samples) if label != 'reference16' else None,
                load_flagged_samples=sum(s['elevated_external_load'] for s in loads),
                external_cpu_percent_machine_median=statistics.median(s['external_cpu_percent_machine_mean'] for s in loads))
            result['primary_timed_arm_samples'] += len(samples)
            result['primary_timed_queries'] += sum(s['completed'] for s in samples)
            result['primary_load_flagged_samples'] += sum(s['elevated_external_load'] for s in loads)
        for name, comparison in case['comparisons'].items():
            a, b = (case['arms'][comparison[k]] for k in ('before_arm', 'after_arm'))
            assert comparison['qps_change_percent'] == (b['qps_median'] / a['qps_median'] - 1) * 100
            assert comparison['cpu_query_change_percent'] == (b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100
            values = comparison['paired_qps_changes_percent']
            assert len(values) == 6
            before, after = (entry['arms'][comparison[k]]['samples'] for k in ('before_arm', 'after_arm'))
            assert values == [(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(before, after)]
            csv_rows.append(dict(rows=entry['rows'], comparison=name,
                before_qps=a['qps_median'], after_qps=b['qps_median'],
                qps_change_percent=comparison['qps_change_percent'], cpu_query_change_percent=comparison['cpu_query_change_percent'],
                paired_qps_min_percent=min(values), paired_qps_max_percent=max(values),
                before_rss_mib=a['rss_bytes_median'] / 2**20, after_rss_mib=b['rss_bytes_median'] / 2**20))
        result['cases'].append(case)
    for entry in data['transitions']:
        assert entry['lifecycle_checks_passed'] and len(entry['phases']) == 3
        assert entry['idle_gate']['idle_percent_mean'] >= 90 and entry['idle_gate']['idle_percent_min'] >= 80
        assert [e['name'] for e in entry['phases']] == ['large', 'hot', 'large-again']
        assert all(0 <= s['cache_used_bytes'] <= 512 * 2**20 for s in entry['memory_samples'])
        telemetry = [json.loads(line) for line in (root / f"sql/transition-{entry['pass_number']}-{entry['arm']}-load.jsonl").read_text().splitlines()]
        phases = []
        for phase in entry['phases']:
            load = sample_load(dict(phase['sample'], round=0), telemetry)
            phases.append(dict(phase, load=load))
            result['diagnostic_timed_arm_samples'] += 1
            result['diagnostic_timed_queries'] += phase['sample']['completed']
            result['diagnostic_load_flagged_samples'] += load['elevated_external_load']
        result['transitions'].append(dict(pass_number=entry['pass_number'], arm=entry['arm'], phases=phases,
            idle_gate=entry['idle_gate'], peak_cache_used_bytes=max(s['cache_used_bytes'] for s in entry['memory_samples'])))
    (root / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    with (root / 'summary.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(json.dumps({k: v for k, v in result.items() if k not in ('cases', 'transitions')}, indent=2))


if __name__ == '__main__':
    main()
