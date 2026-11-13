#!/usr/bin/env python3
"""Paired 0/8/16 MiB block-cache matrix for #5042, with no reader TLS."""
import argparse
from collections import Counter
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
import urllib.parse

import benchmark
import compare_blockcache
import load_telemetry
import scale_benchmark
import support
from benchmark import ReaderServer
from compare_blockcache import lifecycle
from load_telemetry import LoadMonitor
from scale_benchmark import fixed_queries, fixture_info
from support import clone_data, resources

SIZES = (20000, 100000, 500000, 1000000, 5000000)
BUDGETS = (0, 8, 16)
ARMS = {f'{kind}{budget}': {'kind': kind, 'cache_mib': budget}
        for budget in BUDGETS for kind in ('baseline', 'candidate')}


def orders(labels, rounds=6):
    assert rounds == 6 and len(labels) in (2, 6)
    if len(labels) == 2:
        return [labels if n % 2 == 0 else labels[::-1] for n in range(rounds)]
    # Williams design: each arm occupies every position and follows every other arm once.
    base = (0, 1, 5, 2, 4, 3)
    return [[labels[(n + offset) % 6] for n in base] for offset in range(rounds)]


def change(before, after):
    return (after / before - 1) * 100


def compare(entry, before, after):
    a, b = entry['arms'][before], entry['arms'][after]
    return {'before_arm': before, 'after_arm': after,
            'qps_change_percent': change(a['qps_median'], b['qps_median']),
            'server_cpu_change_percent': change(a['server_cpu_ms_per_query_median'], b['server_cpu_ms_per_query_median']),
            'paired_qps_changes_percent': [change(x['qps'], y['qps']) for x, y in zip(a['samples'], b['samples'])]}


def run_case(case, servers, ctx, args, monitor):
    pools = fixed_queries(case['docs'], case.get('count', False))
    entry = {'case': case, 'query_pool_sizes': [len(p) for p in pools],
             'query_set_sha256': hashlib.sha256(b'\n'.join(q[0] for p in pools for q in p)).hexdigest(),
             'arms': {label: {'samples': [], 'pid': db.pid, 'meta': db.sql_all(
                 urllib.parse.parse_qs(pools[0][0][0].decode())['query'][0] + '; SHOW META')[1]['data']}
                      for label, db in servers.items()}}
    go, ready = ctx.Event(), ctx.Queue()
    with ctx.Pool(8, initializer=benchmark.init_worker, initargs=(go, ready)) as pool:
        for repeat, labels in enumerate(orders(list(servers))):
            for label in labels:
                db = servers[label]
                go.clear()
                jobs = [pool.apply_async(benchmark.worker, (db.port, queries, args.duration, False, None)) for queries in pools]
                for _ in jobs:
                    ready.get(timeout=180)
                before = resources(db.pid)
                stamp = time.monotonic()
                started = time.perf_counter()
                go.set()
                replies = [job.get(timeout=args.duration + 30) for job in jobs]
                ended = time.monotonic()
                after = resources(db.pid)
                elapsed = max(r['finished'] for r in replies) - started
                completed = sum(r['completed'] for r in replies)
                latency = [v for r in replies for v in r['latencies_ns']]
                entry['arms'][label]['samples'].append({
                    'round': repeat, 'order': labels, 'completed': completed, 'elapsed_seconds': elapsed,
                    'qps': completed / elapsed,
                    'server_cpu_ms_per_query': (after['cpu_ns'] - before['cpu_ns']) / 1e6 / completed,
                    'client_cpu_cores': sum(r['client_cpu_ns'] for r in replies) / 1e9 / elapsed,
                    'rss_bytes': after['rss_bytes'],
                    'p50_ms': benchmark.quantile(latency, .50) / 1e6,
                    'p95_ms': benchmark.quantile(latency, .95) / 1e6,
                    'p99_ms': benchmark.quantile(latency, .99) / 1e6,
                    'from_monotonic_seconds': stamp, 'to_monotonic_seconds': ended})
    # Keep logging until the last timed interval has a complete telemetry sample.
    deadline = time.monotonic() + 10
    while not monitor.samples or monitor.samples[-1]['monotonic_seconds'] < ended:
        if monitor.error:
            raise monitor.error
        assert time.monotonic() < deadline, 'Telemetry did not cover the final sample'
        time.sleep(.05)
    for a in entry['arms'].values():
        for metric in ('qps', 'server_cpu_ms_per_query', 'p50_ms', 'p95_ms', 'p99_ms', 'rss_bytes'):
            a[metric + '_median'] = statistics.median(s[metric] for s in a['samples'])
    if case.get('aa'):
        entry['aa_comparison'] = compare(entry, 'aa0', 'aa1')
    else:
        entry['implementation_comparisons'] = {str(n): compare(entry, f'baseline{n}', f'candidate{n}') for n in BUDGETS}
        entry['candidate_cache_comparisons'] = {str(n): compare(entry, 'candidate0', f'candidate{n}') for n in (8, 16)}
    return entry


def selfcheck():
    labels = list(ARMS)
    rows = orders(labels)
    assert all(set(row) == set(labels) for row in rows)
    assert all({row[i] for row in rows} == set(labels) for i in range(6))
    assert Counter((a, b) for row in rows for a, b in zip(row, row[1:])) == Counter(
        (a, b) for a in labels for b in labels if a != b)
    assert orders(['a', 'b']).count(['a', 'b']) == 3
    assert abs(change(100, 110) - 10) < 1e-8
    assert len(fixed_queries(20000)) == 8
    load_telemetry.selfcheck()
    print('block-cache budget matrix selfcheck passed', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path, nargs='?')
    p.add_argument('candidate', type=Path, nargs='?')
    p.add_argument('--fixtures', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--rows', nargs='+', type=int, default=SIZES)
    p.add_argument('--duration', type=float, default=3)
    p.add_argument('--reverse', action='store_true')
    p.add_argument('--controls', action='store_true')
    p.add_argument('--selfcheck', action='store_true')
    args = p.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.baseline and args.candidate and args.fixtures and args.output
    assert args.duration > 0 and set(args.rows) <= set(SIZES)
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    scripts = [Path(__file__), Path(benchmark.__file__), Path(compare_blockcache.__file__),
               Path(load_telemetry.__file__), Path(scale_benchmark.__file__), Path(support.__file__)]
    data = {'scope': 'PR #5042; no reader TLS; paired old/new implementation AND 0/8/16 MiB budgets',
            'baseline_source_commit': '1514b3e', 'candidate_source_commit': '376fbf9988b2458ee196a5d92135c35a5121edc7',
            'reader_tls': False, 'docid_lookup_cache_size': 0, 'qcache_max_bytes': 0,
            'rounds': 6, 'seconds_per_arm': args.duration, 'server_threads': 8,
            'payload_bytes': 128, 'block_bytes': 16384, 'compression': 'lz4', 'reader_buffer_budget_bytes': 8388608,
            'platform': platform.platform(), 'order_design': 'six-arm Williams balanced Latin square; 2-arm A/A alternates',
            'reverse': args.reverse, 'all_completed_samples_retained': True,
            'idle_gate': {'seconds': 30, 'mean_idle_percent': 90, 'minimum_idle_percent': 80, 'timeout_seconds': 600},
            'load_flag': 'sample mean external CPU >10% of machine or one-second peak >20%; annotation only',
            'calibration': {k: v for k, v in os.environ.items() if k.startswith('MANTICORE_')},
            'binaries': {k: {'path': str(v), 'sha256': hashlib.sha256(v.read_bytes()).hexdigest()} for k, v in binaries.items()},
            'scripts_sha256': {s.name: hashlib.sha256(s.read_bytes()).hexdigest() for s in scripts},
            'fixtures': {}, 'cases': []}
    cases = [dict(name=f'rows{n}', docs=n, batch=256, clients=8) for n in args.rows]
    if args.controls:
        cases += [dict(name='count-1000000', docs=1000000, batch=256, clients=8, count=True),
                  dict(name='aa-1000000-cache8', docs=1000000, batch=256, clients=8, aa=True)]
    if args.reverse:
        cases.reverse()
    ctx = mp.get_context('spawn')
    for number, case in enumerate(cases):
        fixture = args.fixtures / f"fixture-{case['docs']}"
        data['fixtures'][str(case['docs'])] = fixture_info(fixture, case['docs'])
        arm_info = {k: dict(v) for k, v in ARMS.items()}
        if case.get('aa'):
            arm_info = {f'aa{n}': {'kind': 'candidate', 'cache_mib': 8} for n in (0, 1)}
        labels = list(arm_info)
        labels = labels[number % len(labels):] + labels[:number % len(labels)]
        if args.reverse:
            labels.reverse()
        with tempfile.TemporaryDirectory(prefix='block-budget-') as temp, ExitStack() as stack:
            servers = {}
            for label in labels:
                spec = arm_info[label]
                folder = Path(temp) / label
                folder.mkdir()
                clone_data(fixture, folder)
                servers[label] = stack.enter_context(ReaderServer(str(binaries[spec['kind']]), folder,
                    spec['cache_mib'] * 2**20, docid_cache=0).running())
            path = args.output.with_name(args.output.stem + '-' + case['name'] + '-load.jsonl')
            with LoadMonitor(path) as monitor:
                print('waiting for idle gate', case['name'], flush=True)
                gate = monitor.wait_idle(seconds=30, mean_idle=90, min_idle=80, timeout=600)
                print('starting', case['name'], 'idle mean', round(gate['idle_percent_mean'], 2), flush=True)
                entry = run_case(case, servers, ctx, args, monitor)
                entry['arm_configuration'] = arm_info
                entry['load_control'] = {'idle_gate': gate, 'telemetry': path.name, 'thermal_before': monitor.thermal_before}
            entry['load_control']['thermal_after'] = monitor.thermal_after
            for label, db in servers.items():
                used = int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value'])
                assert used == 0
                entry['arms'][label]['docid_cache_used_bytes'] = used
                lifecycle(db, case['docs'])
            entry['lifecycle_checks_passed'] = True
            data['cases'].append(entry)
            args.output.write_text(json.dumps(data, indent=2) + '\n')
            print(case['name'], 'QPS:', {k: round(a['qps_median'], 1) for k, a in entry['arms'].items()}, flush=True)
    data['completed'] = True
    args.output.write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    main()
