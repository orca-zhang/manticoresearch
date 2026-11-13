#!/usr/bin/env python3
"""Repeat the latest-cache TLS comparison with an idle gate and host-load telemetry."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time

from load_telemetry import LoadMonitor

import benchmark
import scale_benchmark
import support
from benchmark import ReaderServer, queries_for, run_case
from compare_blockcache import lifecycle
from scale_benchmark import fixed_queries, fixture_info
from support import clone_data


def cases():
    result = []
    for docs in (20000, 100000, 500000, 1000000, 5000000):
        for cache in (0, 16777216, 134217728):
            result.append(dict(name=f'rows{docs}-cache{cache}', docs=docs, cache=cache, clients=8, batch=256))
    result.append(dict(name='rows5000000-cache536870912', docs=5000000, cache=536870912, clients=8, batch=256))
    for docs in (20000, 1000000):
        result.append(dict(name=f'count-{docs}', docs=docs, cache=16777216, clients=8, batch=256, count=True))
        result.append(dict(name=f'point-{docs}', docs=docs, cache=16777216, clients=8, batch=1))
    result.append(dict(name='aa-1000000', docs=1000000, cache=16777216, clients=8, batch=256, aa=True))
    result.append(dict(name='mixed-1000000', docs=1000000, cache=16777216, clients=8, batch=256, mixed=True))
    return result


def pools_for(case):
    if case.get('mixed'):
        return [queries_for(case['docs'], 256 if i < 4 else 1, i, hot=i >= 4) for i in range(8)]
    if case['batch'] == 256:
        return fixed_queries(case['docs'], case.get('count', False))
    return [queries_for(case['docs'], case['batch'], i) for i in range(case['clients'])]


def selfcheck():
    matrix = cases()
    assert len(matrix) == len({c['name'] for c in matrix}) == 22
    assert sum(c['name'].startswith('rows') for c in matrix) == 16
    for c in matrix:
        pools = pools_for(c)
        assert len(pools) == c['clients']
        for i, pool in enumerate(pools):
            expected_rows = 1 if c.get('count') or (c.get('mixed') and i >= 4) else c['batch']
            assert all(len(expected) == expected_rows for _, expected in pool)
    assert all(len(q) == 20 for q in pools_for(matrix[0]))
    print('latest-block-cache TLS harness selfcheck passed', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference', type=Path, nargs='?')
    p.add_argument('tls', type=Path, nargs='?')
    p.add_argument('--fixtures', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--rounds', type=int, default=6)
    p.add_argument('--duration', type=float, default=3)
    p.add_argument('--order-offset', type=int, default=0)
    p.add_argument('--cases', nargs='+')
    p.add_argument('--selfcheck', action='store_true')
    p.add_argument('--reverse-cases', action='store_true')
    args = p.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.reference and args.tls and args.fixtures and args.output
    assert args.rounds >= 2 and args.duration > 0
    selected = [c for c in cases() if args.cases is None or c['name'] in args.cases]
    assert selected and (args.cases is None or len(selected) == len(args.cases))
    if args.reverse_cases:
        selected.reverse()
        # Preserve per-case starting-arm semantics when case order is reversed.
        args.order_offset ^= (len(selected) - 1) % 2
    binaries = {'reference': str(args.reference.resolve()), 'tls': str(args.tls.resolve())}
    scripts = [Path(__file__), Path(benchmark.__file__), Path(scale_benchmark.__file__), Path(support.__file__),
               Path(__file__).parent / 'compare_blockcache.py', Path(__file__).parent / 'load_telemetry.py']
    output = {'comparison': 'Latest shared XXH3/sharded block cache in BOTH arms; only reader TLS differs',
              'baseline_source_commit': '376fbf9988b2458ee196a5d92135c35a5121edc7',
              'reader_tls_patch_commit': '019868e9f79d1bb2bd1f96dafb88ef20acd45418',
              'block_cache_implementation': 'shared sharded LRU with seeded XXH3-64, up to 16 shards',
              'docid_lookup_cache_size': 0, 'qcache_max_bytes': 0, 'reader_buffer_budget_bytes': 8388608,
              'platform': platform.platform(), 'rounds': args.rounds, 'seconds_per_arm': args.duration,
              'server_threads': 8, 'payload_bytes': 128, 'block_bytes': 16384, 'compression': 'lz4',
              'aa_note': 'A/A runs the reference binary in both arms.',
              'calibration': {k: v for k, v in os.environ.items() if k.startswith('MANTICORE_')},
              'scripts_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts},
              'binaries': {k: {'path': v, 'sha256': hashlib.sha256(Path(v).read_bytes()).hexdigest()}
                           for k, v in binaries.items()}, 'fixtures': {}, 'cases': [],
              'load_control': {'idle_gate': '60 seconds, >=90% system idle on average and no interval below 80%',
                               'idle_timeout_seconds': 900, 'no_samples_discarded': True,
                               'source_unchanged': True, 'test_mode': False,
                               'uid_seed_note': 'Normal --nodetach startup; runtime index IDs not instrumented. No startup-dependent shard-routing variation is claimed.'}}
    ctx = mp.get_context('spawn')
    initial_order = args.order_offset
    for case in selected:
        fixture = args.fixtures / f"fixture-{case['docs']}"
        assert fixture.is_dir(), fixture
        output['fixtures'][str(case['docs'])] = fixture_info(fixture, case['docs'])
        with tempfile.TemporaryDirectory(prefix='tls-latest-block-') as temp, ExitStack() as stack:
            servers = {}
            for label, binary in binaries.items():
                folder = Path(temp) / label
                folder.mkdir()
                clone_data(fixture, folder)
                if case.get('aa'):
                    binary = binaries['reference']
                servers[label] = stack.enter_context(ReaderServer(binary, folder, case['cache'], docid_cache=0).running())
            args.order_offset = (initial_order + len(output['cases'])) % 2
            print('waiting for idle gate', case['name'], flush=True)
            with LoadMonitor(args.output.with_name(args.output.stem + '-' + case['name'] + '-load.jsonl')) as monitor:
                gate = monitor.wait_idle(seconds=60, mean_idle=90, min_idle=80, timeout=900)
                print('starting', case['name'], 'idle gate:', round(gate['idle_percent_mean'], 2), flush=True)
                wrapped_resources = benchmark.resources
                sample_markers = []
                def measured_resources(pid):
                    stamp = {'pid': pid, 'monotonic_seconds': time.monotonic(), 'wall_time_ns': time.time_ns()}
                    result = wrapped_resources(pid)
                    sample_markers.append(stamp)
                    return result
                benchmark.resources = measured_resources
                try:
                    entry = run_case(case, servers, ctx, args, query_sets=pools_for(case))
                finally:
                    benchmark.resources = wrapped_resources
                assert len(sample_markers) == args.rounds * 4
                entry['load_control'] = {'idle_gate': gate, 'timed_sample_markers': sample_markers,
                                         'telemetry': monitor.path.name, 'thermal_before': monitor.thermal_before}
            entry['load_control']['thermal_after'] = monitor.thermal_after
            for label, db in servers.items():
                arm = entry['arms'][label]
                arm['rss_bytes_median'] = statistics.median(s['rss_bytes'] for s in arm['samples'])
                arm['docid_cache_used_bytes'] = int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value'])
                assert arm['docid_cache_used_bytes'] == 0
                lifecycle(db, case['docs'])
            entry['lifecycle_checks_passed'] = True
            output['cases'].append(entry)
            args.output.write_text(json.dumps(output, indent=2) + '\n')
            print(f"{case['name']}: {entry['arms']['reference']['qps_median']:.1f} -> "
                  f"{entry['arms']['tls']['qps_median']:.1f} QPS "
                  f"({entry['qps_change_percent']:+.2f}%), CPU/query "
                  f"{entry['server_cpu_change_percent']:+.2f}%", flush=True)
    output['completed'] = True
    args.output.write_text(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()
