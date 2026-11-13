#!/usr/bin/env python3
"""Compare manual/adaptive decoded-block caching and record hot-set transitions."""
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
import threading
import time
import urllib.parse

import benchmark
import block_cache_budgets
import compare_blockcache
import load_telemetry
import scale_benchmark
import support
from benchmark import ReaderServer
from block_cache_budgets import orders
from compare_blockcache import lifecycle
from load_telemetry import LoadMonitor
from scale_benchmark import fixed_queries, fixture_info
from support import clone_data, resources

ARMS = {
    'reference16': dict(binary='reference', cache_mib=16, adaptive=False),
    'manual16': dict(binary='candidate', cache_mib=16, adaptive=False),
    'manual512': dict(binary='candidate', cache_mib=512, adaptive=False),
    'adaptive512': dict(binary='candidate', cache_mib=512, adaptive=True),
    'off0': dict(binary='candidate', cache_mib=0, adaptive=False),
    'off1': dict(binary='candidate', cache_mib=0, adaptive=True),
}
PAIRS = {'manual16_regression': ('reference16', 'manual16'),
         'adaptive512': ('manual512', 'adaptive512'),
         'capacity16_to512': ('manual16', 'manual512'),
         'off_to_manual512': ('off0', 'manual512'),
         'off_to_adaptive512': ('off0', 'adaptive512'),
         'cache_off_control': ('off0', 'off1')}


def cache_used(db, spec):
    if spec['binary'] == 'reference':
        return None
    used = int(db.sql("SHOW STATUS LIKE 'docstore_cache_used_bytes'")['data'][0]['Value'])
    assert 0 <= used <= spec['cache_mib'] * 2**20
    return used


def server(stack, folder, fixture, binaries, spec):
    folder.mkdir()
    clone_data(fixture, folder)
    db = ReaderServer(str(binaries[spec['binary']]), folder, spec['cache_mib'] * 2**20, docid_cache=0)
    if spec['binary'] == 'candidate':
        db.config.write_text(db.config.read_text().replace(
            'buddy_path =', f"docstore_cache_adaptive = {int(spec['adaptive'])}\nbuddy_path ="))
    return stack.enter_context(db.running())


def measure(db, pools, ctx, duration):
    go, ready = ctx.Event(), ctx.Queue()
    with ctx.Pool(8, initializer=benchmark.init_worker, initargs=(go, ready)) as pool:
        jobs = [pool.apply_async(benchmark.worker, (db.port, queries, duration, False, None)) for queries in pools]
        for _ in jobs:
            ready.get(timeout=180)
        before = resources(db.pid)
        stamp = time.monotonic()
        started = time.perf_counter()
        go.set()
        replies = [job.get(timeout=duration + 30) for job in jobs]
        ended = time.monotonic()
        after = resources(db.pid)
    elapsed = max(r['finished'] for r in replies) - started
    completed = sum(r['completed'] for r in replies)
    latency = [n for r in replies for n in r['latencies_ns']]
    return dict(completed=completed, elapsed_seconds=elapsed, qps=completed / elapsed,
                server_cpu_ms_per_query=(after['cpu_ns'] - before['cpu_ns']) / 1e6 / completed,
                rss_bytes=after['rss_bytes'], p95_ms=benchmark.quantile(latency, .95) / 1e6,
                client_cpu_cores=sum(r['client_cpu_ns'] for r in replies) / 1e9 / elapsed,
                from_monotonic_seconds=stamp, to_monotonic_seconds=ended)


def cover_final(monitor, ended):
    deadline = time.monotonic() + 10
    while not monitor.samples or monitor.samples[-1]['monotonic_seconds'] < ended:
        if monitor.error:
            raise monitor.error
        assert time.monotonic() < deadline
        time.sleep(.05)


def matrix_case(rows, number, binaries, args, ctx):
    pools = fixed_queries(rows)
    result = dict(rows=rows, arms={}, arm_configuration=ARMS,
                  fixture=fixture_info(args.fixtures / f'fixture-{rows}', rows),
                  query_set_sha256=hashlib.sha256(b'\n'.join(q[0] for p in pools for q in p)).hexdigest())
    labels = list(ARMS)
    labels = labels[number % 6:] + labels[:number % 6]
    with tempfile.TemporaryDirectory(prefix='adaptive-matrix-') as temp, ExitStack() as stack:
        servers = {label: server(stack, Path(temp) / label, args.fixtures / f'fixture-{rows}', binaries, ARMS[label]) for label in labels}
        with LoadMonitor(args.output / f'matrix-{rows}-load.jsonl') as monitor:
            print('waiting for matrix idle gate', rows, flush=True)
            result['idle_gate'] = monitor.wait_idle(seconds=30, mean_idle=90, min_idle=80, timeout=600)
            print('starting matrix', rows, flush=True)
            for label in labels:
                sql = urllib.parse.parse_qs(pools[0][0][0].decode())['query'][0]
                result['arms'][label] = dict(samples=[], pid=servers[label].pid,
                    meta=servers[label].sql_all(sql + '; SHOW META')[1]['data'])
            for repeat, order in enumerate(orders(labels)):
                for label in order:
                    sample = measure(servers[label], pools, ctx, args.duration)
                    sample.update(round=repeat, order=order, cache_used_bytes=cache_used(servers[label], ARMS[label]))
                    result['arms'][label]['samples'].append(sample)
            cover_final(monitor, sample['to_monotonic_seconds'])
        result['thermal_before'], result['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        for label, db in servers.items():
            arm = result['arms'][label]
            for metric in ['qps', 'server_cpu_ms_per_query', 'rss_bytes', 'p95_ms']:
                arm[metric + '_median'] = statistics.median(s[metric] for s in arm['samples'])
            assert int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value']) == 0
            lifecycle(db, rows)
        result['lifecycle_checks_passed'] = True
    result['comparisons'] = {}
    for name, (before, after) in PAIRS.items():
        a, b = result['arms'][before], result['arms'][after]
        result['comparisons'][name] = dict(before_arm=before, after_arm=after,
            qps_change_percent=(b['qps_median'] / a['qps_median'] - 1) * 100,
            cpu_query_change_percent=(b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100,
            paired_qps_changes_percent=[(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a['samples'], b['samples'])])
    print('matrix', rows, {k: round(a['qps_median'], 1) for k, a in result['arms'].items()}, flush=True)
    return result


def transition(pass_number, label, binaries, args, ctx):
    spec = ARMS[label]
    result = dict(pass_number=pass_number, arm=label, configuration=spec, phases=[], memory_samples=[])
    with tempfile.TemporaryDirectory(prefix='adaptive-transition-') as temp, ExitStack() as stack:
        db = server(stack, Path(temp) / label, args.fixtures / 'fixture-5000000', binaries, spec)
        with LoadMonitor(args.output / f'transition-{pass_number}-{label}-load.jsonl') as monitor:
            print('waiting for transition idle gate', pass_number, label, flush=True)
            result['idle_gate'] = monitor.wait_idle(seconds=30, mean_idle=90, min_idle=80, timeout=600)
            stop, errors, stage = threading.Event(), [], ['startup']
            def sample_memory():
                try:
                    while not stop.is_set():
                        used = cache_used(db, spec)
                        result['memory_samples'].append(dict(monotonic_seconds=time.monotonic(), stage=stage[0],
                                                             cache_used_bytes=used, rss_bytes=resources(db.pid)['rss_bytes']))
                        stop.wait(.2)
                except BaseException as error:
                    errors.append(repr(error))
            thread = threading.Thread(target=sample_memory)
            thread.start()
            try:
                for name, rows in [('large', 5000000), ('hot', 20000), ('large-again', 5000000)]:
                    stage[0] = name
                    began = time.monotonic()
                    sample = measure(db, fixed_queries(rows), ctx, 8)
                    result['phases'].append(dict(name=name, queried_id_range=rows, from_before_warmup=began,
                                                 sample=sample, used_bytes_after=cache_used(db, spec)))
                cover_final(monitor, sample['to_monotonic_seconds'])
            finally:
                stop.set()
                thread.join(timeout=10)
                assert not thread.is_alive()
            assert not errors, errors
            assert result['memory_samples']
        result['thermal_before'], result['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        lifecycle(db, 5000000)
        result['lifecycle_checks_passed'] = True
    print('transition', pass_number, label, [(p['name'], round(p['used_bytes_after'] / 2**20, 2)) for p in result['phases']], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path, nargs='?')
    parser.add_argument('candidate', type=Path, nargs='?')
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--duration', type=float, default=3)
    parser.add_argument('--rows', nargs='+', type=int, default=scale_benchmark.SIZES)
    parser.add_argument('--matrix-only', action='store_true')
    parser.add_argument('--selfcheck', action='store_true')
    args = parser.parse_args()
    if args.selfcheck:
        block_cache_budgets.selfcheck()
        assert set(ARMS) == {n for pair in PAIRS.values() for n in pair}
        assert ARMS['adaptive512']['cache_mib'] == ARMS['manual512']['cache_mib'] == 512
        print('Adaptive matrix pair/configuration selfcheck passed.')
        return
    assert args.reference and args.candidate and args.fixtures and args.output
    assert args.duration > 0 and set(args.rows) <= set(scale_benchmark.SIZES)
    args.output.mkdir(parents=True, exist_ok=True)
    binaries = dict(reference=args.reference.resolve(), candidate=args.candidate.resolve())
    scripts = [Path(__file__), *[Path(m.__file__) for m in [benchmark, block_cache_budgets, compare_blockcache, load_telemetry, scale_benchmark, support]]]
    data = dict(reader_tls=False, docid_lookup_cache_size=0, qcache_max_bytes=0, rounds=6,
                seconds_per_arm=args.duration, all_completed_samples_retained=True,
                platform=platform.platform(), clients=8, server_workers=8, returned_rows=256,
                payload_bytes=128, block_bytes=16384, compression='lz4', reader_buffer_budget_bytes=8388608,
                comparison_pairs=PAIRS, block_cache_configurations=ARMS,
                baseline_source_commit='376fbf9988b2458ee196a5d92135c35a5121edc7',
                candidate_source='same baseline plus archived adaptive-cache patch',
                calibration={k: v for k, v in os.environ.items() if k.startswith('MANTICORE_')},
                binary_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in binaries.items()},
                scripts_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts},
                cases=[], transitions=[])
    ctx = mp.get_context('spawn')
    for number, rows in enumerate(args.rows):
        data['cases'].append(matrix_case(rows, number, binaries, args, ctx))
        (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')
    if not args.matrix_only:
        for pass_number, labels in [(1, ['manual512', 'adaptive512']), (2, ['adaptive512', 'manual512'])]:
            for label in labels:
                data['transitions'].append(transition(pass_number, label, binaries, args, ctx))
                (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')
    data['completed'] = True
    (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    main()
