#!/usr/bin/env python3
"""Compare default caching, heap adaptation and VM-backed adaptation with RSS evidence."""
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

import adaptive_cache
import benchmark
import block_cache_budgets
import compare_blockcache
import load_telemetry
import scale_benchmark
import support
from adaptive_cache import measure, cover_final
from benchmark import ReaderServer
from block_cache_budgets import orders
from compare_blockcache import lifecycle
from load_telemetry import LoadMonitor
from scale_benchmark import fixed_queries, fixture_info
from support import clone_data, resources

ARMS = {
    'default16': dict(binary='reference', cache_mib=16, adaptive=False),
    'heap_manual512': dict(binary='heap', cache_mib=512, adaptive=False),
    'heap_adaptive512': dict(binary='heap', cache_mib=512, adaptive=True),
    'vm_adaptive16': dict(binary='candidate', cache_mib=16, adaptive=True),
    'vm_adaptive512': dict(binary='candidate', cache_mib=512, adaptive=True),
    'cache_off': dict(binary='candidate', cache_mib=0, adaptive=True),
}
PAIRS = {
    'default_to_adaptive16': ('default16', 'vm_adaptive16'),
    'default_to_adaptive512': ('default16', 'vm_adaptive512'),
    'heap_to_vm_adaptive512': ('heap_adaptive512', 'vm_adaptive512'),
    'manual_to_vm_adaptive512': ('heap_manual512', 'vm_adaptive512'),
    'heap_adaptive_policy512': ('heap_manual512', 'heap_adaptive512'),
    'vm_capacity16_to512': ('vm_adaptive16', 'vm_adaptive512'),
    'off_to_vm16': ('cache_off', 'vm_adaptive16'),
    'off_to_vm512': ('cache_off', 'vm_adaptive512'),
}


def stats(db, spec):
    values = {x['Counter']: int(x['Value']) for x in db.sql("SHOW STATUS LIKE 'docstore_cache_%'")['data']}
    result = {name: values.get('docstore_cache_' + name) for name in ['used_bytes', 'mapped_bytes', 'spare_bytes']}
    if spec['binary'] != 'reference':
        assert 0 <= result['used_bytes'] <= spec['cache_mib'] * 2**20
    if spec['binary'] == 'candidate':
        assert 0 <= result['spare_bytes'] <= 16 * 64 * 1024
        assert result['mapped_bytes'] >= result['spare_bytes']
    return result


def server(stack, folder, fixture, binaries, spec):
    folder.mkdir()
    clone_data(fixture, folder)
    db = ReaderServer(str(binaries[spec['binary']]), folder, spec['cache_mib'] * 2**20, docid_cache=0)
    if spec['binary'] != 'reference':
        db.config.write_text(db.config.read_text().replace('buddy_path =',
            f"docstore_cache_adaptive = {int(spec['adaptive'])}\nbuddy_path ="))
    return stack.enter_context(db.running())


def matrix_case(rows, number, binaries, args, ctx):
    pools = fixed_queries(rows)
    labels = list(ARMS)
    labels = labels[number % 6:] + labels[:number % 6]
    result = dict(rows=rows, arm_configuration=ARMS, arms={},
                  fixture=fixture_info(args.fixtures / f'fixture-{rows}', rows),
                  query_set_sha256=hashlib.sha256(b'\n'.join(q[0] for p in pools for q in p)).hexdigest())
    journal = args.output / f'matrix-{rows}-samples.jsonl'
    assert not journal.exists(), journal
    with tempfile.TemporaryDirectory(prefix='vm-cache-matrix-') as temp, ExitStack() as stack:
        servers = {n: server(stack, Path(temp) / n, args.fixtures / f'fixture-{rows}', binaries, ARMS[n]) for n in labels}
        with LoadMonitor(args.output / f'matrix-{rows}-load.jsonl') as monitor:
            print('waiting for matrix idle gate', rows, flush=True)
            result['idle_gate'] = monitor.wait_idle(seconds=30, mean_idle=90, min_idle=80, timeout=600)
            print('starting matrix', rows, flush=True)
            for label, db in servers.items():
                sql = urllib.parse.parse_qs(pools[0][0][0].decode())['query'][0]
                result['arms'][label] = dict(samples=[], pid=db.pid, meta=db.sql_all(sql + '; SHOW META')[1]['data'])
            for repeat, order in enumerate(orders(labels)):
                for label in order:
                    sample = measure(servers[label], pools, ctx, args.duration)
                    sample.update(round=repeat, order=order, cache=stats(servers[label], ARMS[label]))
                    result['arms'][label]['samples'].append(sample)
                    with journal.open('a') as stream:
                        stream.write(json.dumps(dict(arm=label, sample=sample)) + '\n')
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
        a, b = (result['arms'][n] for n in (before, after))
        result['comparisons'][name] = dict(before_arm=before, after_arm=after,
            qps_change_percent=(b['qps_median'] / a['qps_median'] - 1) * 100,
            cpu_query_change_percent=(b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100,
            paired_qps_changes_percent=[(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a['samples'], b['samples'])])
    print('matrix', rows, {k: round(a['qps_median'], 1) for k, a in result['arms'].items()}, flush=True)
    return result


def transition(pass_number, label, binaries, args, ctx):
    spec = ARMS[label]
    result = dict(pass_number=pass_number, arm=label, configuration=spec, phases=[], memory_samples=[])
    with tempfile.TemporaryDirectory(prefix='vm-cache-transition-') as temp, ExitStack() as stack:
        db = server(stack, Path(temp) / label, args.fixtures / 'fixture-5000000', binaries, spec)
        with LoadMonitor(args.output / f'transition-{pass_number}-{label}-load.jsonl') as monitor:
            print('waiting for transition idle gate', pass_number, label, flush=True)
            result['idle_gate'] = monitor.wait_idle(seconds=30, mean_idle=90, min_idle=80, timeout=600)
            stop, errors, stage = threading.Event(), [], ['startup']
            def probe():
                try:
                    while not stop.is_set():
                        cache = stats(db, spec)
                        usage = resources(db.pid)
                        result['memory_samples'].append(dict(monotonic_seconds=time.monotonic(), stage=stage[0],
                            cache=cache, rss_bytes=usage['rss_bytes'], footprint_bytes=usage.get('footprint_bytes')))
                        stop.wait(.2)
                except BaseException as error:
                    errors.append(repr(error))
            thread = threading.Thread(target=probe)
            thread.start()
            try:
                for name, rows in [('large', 5000000), ('hot', 20000), ('large-again', 5000000)]:
                    stage[0] = name
                    began = time.monotonic()
                    sample = measure(db, fixed_queries(rows), ctx, 8)
                    result['phases'].append(dict(name=name, queried_id_range=rows, from_before_warmup=began,
                        sample=sample, cache_after=stats(db, spec), usage_after=resources(db.pid)))
                cover_final(monitor, sample['to_monotonic_seconds'])
            finally:
                stop.set()
                thread.join(timeout=10)
                assert not thread.is_alive()
            assert not errors and result['memory_samples'], errors
        result['thermal_before'], result['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        lifecycle(db, 5000000)
        result['lifecycle_checks_passed'] = True
    print('transition', pass_number, label,
          [(p['name'], round(p['cache_after']['used_bytes'] / 2**20, 2), round(p['usage_after']['rss_bytes'] / 2**20, 2))
           for p in result['phases']], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['reference', 'heap', 'candidate']:
        parser.add_argument(name, type=Path, nargs='?')
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
        assert ARMS['default16']['cache_mib'] == ARMS['vm_adaptive16']['cache_mib'] == 16
        assert all(ARMS[n]['cache_mib'] == 512 for n in ['heap_manual512', 'heap_adaptive512', 'vm_adaptive512'])
        print('VM-cache equal-budget and comparison selfcheck passed.')
        return
    assert args.reference and args.heap and args.candidate and args.fixtures and args.output
    assert args.duration > 0 and set(args.rows) <= set(scale_benchmark.SIZES)
    args.output.mkdir(parents=True, exist_ok=True)
    binaries = {n: getattr(args, n).resolve() for n in ['reference', 'heap', 'candidate']}
    scripts = [Path(__file__), *[Path(m.__file__) for m in [adaptive_cache, benchmark, block_cache_budgets,
               compare_blockcache, load_telemetry, scale_benchmark, support]]]
    data = dict(reader_tls=False, docid_lookup_cache_size=0, qcache_max_bytes=0, rounds=6,
        seconds_per_arm=args.duration, all_completed_samples_retained=True, platform=platform.platform(),
        clients=8, server_workers=8, returned_rows=256, payload_bytes=128, block_bytes=16384,
        compression='lz4', reader_buffer_budget_bytes=8388608, comparison_pairs=PAIRS, configurations=ARMS,
        pool_region_bytes=65536, small_size_class_bytes=256, small_payload_threshold_bytes=31744,
        calibration={k: v for k, v in os.environ.items() if k.startswith('MANTICORE_')},
        binary_sha256={n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in binaries.items()},
        scripts_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts}, cases=[], transitions=[])
    ctx = mp.get_context('spawn')
    for number, rows in enumerate(args.rows):
        data['cases'].append(matrix_case(rows, number, binaries, args, ctx))
        (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')
    if not args.matrix_only:
        for pass_number, labels in [(1, ['heap_adaptive512', 'vm_adaptive512']),
                                   (2, ['vm_adaptive512', 'heap_adaptive512'])]:
            for label in labels:
                data['transitions'].append(transition(pass_number, label, binaries, args, ctx))
                (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')
    data['completed'] = True
    (args.output / 'matrix.json').write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    main()
