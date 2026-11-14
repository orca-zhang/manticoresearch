#!/usr/bin/env python3
"""Final #5042: one binary, capacity/admission controls, and OS-memory return."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'driver'))
import benchmark
from benchmark import ReaderServer, value, make_fixture
from block_cache_budgets import orders
from compare_blockcache import lifecycle
from load_telemetry import LoadMonitor
from scale_benchmark import fixture_info
from support import resources

ARMS = {'off': (0, True), 'manual16': (16, False), 'adaptive16': (16, True),
        'adaptive128': (128, True), 'manual512': (512, False), 'adaptive512': (512, True)}


def encoded(ids):
    sql = 'SELECT id,body FROM docs WHERE id IN (' + ','.join(map(str, ids)) + ') ORDER BY id ASC LIMIT 256'
    return urllib.parse.urlencode({'query': sql}).encode(), [{'id': i, 'body': value(i)} for i in ids]


def queries(rows):
    rng = random.Random(20261114)
    return [[encoded(sorted(rng.sample(range(1, rows + 1), 256))) for _ in range(64)] for _ in range(8)]


class ScanQueries:
    def __init__(self, rows, worker, phase):
        self.rows, self.worker, self.phase = rows, worker, phase
    def __len__(self):
        return 1 << 30
    def __iter__(self):
        for i in range(16): yield self[i]
    def __getitem__(self, index):
        slot = (self.phase * 100000 + index * 8 + self.worker) % (self.rows // 256)
        start = slot * 256 + 1
        return encoded(range(start, start + 256))


def clone(source, target):
    source = source.resolve()
    subprocess.run(['/bin/cp', '-cR', str(source / 'data'), str(target / 'data')], check=True)
    for p in (target / 'data').rglob('*.json'):
        p.write_text(p.read_text().replace(str(source / 'data'), str(target / 'data')))


def start(stack, folder, rows, label):
    folder.mkdir()
    clone(ROOT / 'fixtures' / f'fixture-{rows}', folder)
    capacity, adaptive = ARMS[label]
    db = ReaderServer(str(ROOT / 'searchd'), folder, capacity * 2**20, docid_cache=0)
    db.config.write_text(db.config.read_text().replace('buddy_path =', f'docstore_cache_adaptive = {int(adaptive)}\nbuddy_path ='))
    return stack.enter_context(db.running())


def stats(db, label):
    raw = {x['Counter']: int(x['Value']) for x in db.sql("SHOW STATUS LIKE 'docstore_cache_%'")['data']}
    result = {key: raw['docstore_cache_' + key] for key in ('used_bytes', 'mapped_bytes', 'spare_bytes')}
    assert 0 <= result['used_bytes'] <= ARMS[label][0] * 2**20
    assert 0 <= result['spare_bytes'] <= 16 * 65536
    return result


def measure(db, pools, ctx, duration):
    go, ready = ctx.Event(), ctx.Queue()
    with ctx.Pool(8, initializer=benchmark.init_worker, initargs=(go, ready)) as pool:
        jobs = [pool.apply_async(benchmark.worker, (db.port, p, duration, False, None)) for p in pools]
        for _ in jobs: ready.get(timeout=180)
        before = resources(db.pid)
        stamp, began = time.monotonic(), time.perf_counter()
        go.set()
        replies = [j.get(timeout=duration + 30) for j in jobs]
        ended, after = time.monotonic(), resources(db.pid)
    elapsed = max(r['finished'] for r in replies) - began
    completed = sum(r['completed'] for r in replies)
    return dict(qps=completed / elapsed, completed=completed, elapsed_seconds=elapsed,
                cpu_ms_per_query=(after['cpu_ns'] - before['cpu_ns']) / 1e6 / completed,
                rss_bytes=after['rss_bytes'], footprint_bytes=after.get('footprint_bytes'),
                p95_ms=benchmark.quantile([v for r in replies for v in r['latencies_ns']], .95) / 1e6,
                from_monotonic_seconds=stamp, to_monotonic_seconds=ended)


def cover(monitor, end):
    deadline = time.monotonic() + 10
    while not monitor.samples or monitor.samples[-1]['monotonic_seconds'] < end:
        if monitor.error: raise monitor.error
        assert time.monotonic() < deadline
        time.sleep(.05)


def annotate(samples, path):
    telemetry = [json.loads(x) for x in path.read_text().splitlines()]
    for s in samples:
        overlap = [x for x in telemetry if x['monotonic_seconds'] >= s['from_monotonic_seconds']
                   and x['monotonic_seconds'] - x['interval_seconds'] <= s['to_monotonic_seconds']]
        assert overlap
        s['external_mean_machine_percent'] = statistics.mean(x['external_cpu_percent_machine'] for x in overlap)
        s['external_peak_machine_percent'] = max(x['external_cpu_percent_machine'] for x in overlap)
        s['quality_flag'] = s['external_mean_machine_percent'] > 10 or s['external_peak_machine_percent'] > 20


def matrix(rows, number, args, ctx, workload='random'):
    name = f'{workload}-{rows}'
    result = dict(name=name, rows=rows, arms={}, fixture=fixture_info(ROOT / 'fixtures' / f'fixture-{rows}', rows))
    labels = list(ARMS)
    labels = labels[number % 6:] + labels[:number % 6]
    pools = queries(rows) if workload == 'random' else None
    if pools: result['query_sha256'] = hashlib.sha256(b'\n'.join(q[0] for p in pools for q in p)).hexdigest()
    path = args.output / (name + '-load.jsonl')
    journal = args.output / (name + '-samples.jsonl')
    with tempfile.TemporaryDirectory(dir=ROOT, prefix='matrix-') as temp, ExitStack() as stack:
        servers = {label: start(stack, Path(temp) / label, rows, label) for label in labels}
        for label, db in servers.items():
            result['arms'][label] = dict(samples=[], config=db.config.read_text())
        with LoadMonitor(path) as monitor:
            print('Idle gate:', name, flush=True)
            result['idle_gate'] = monitor.wait_idle(30, 90, 80, 600)
            for repeat, order in enumerate(orders(labels)):
                current = pools if pools else [ScanQueries(rows, worker, repeat) for worker in range(8)]
                for label in order:
                    sample = measure(servers[label], current, ctx, args.duration)
                    sample.update(round=repeat, order=order, cache=stats(servers[label], label))
                    result['arms'][label]['samples'].append(sample)
                    with journal.open('a') as f: f.write(json.dumps({'arm': label, 'sample': sample}) + '\n')
                print('Round', repeat + 1, name, flush=True)
            cover(monitor, sample['to_monotonic_seconds'])
        result['thermal_before'], result['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        for label, db in servers.items():
            arm = result['arms'][label]
            annotate(arm['samples'], path)
            for key in ('qps', 'cpu_ms_per_query', 'rss_bytes', 'footprint_bytes', 'p95_ms'):
                arm[key] = statistics.median(s[key] for s in arm['samples'])
            assert int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")['data'][0]['Value']) == 0
            lifecycle(db, rows)
        result['lifecycle_passed'] = True
    print('RESULT', name, {k: round(a['qps'], 1) for k, a in result['arms'].items()}, flush=True)
    return result


def transition(number, label, args, ctx):
    result = dict(pass_number=number, arm=label, stages=[], memory_samples=[])
    rows = 5000000
    path = args.output / f'memory-{number}-{label}-load.jsonl'
    with tempfile.TemporaryDirectory(dir=ROOT, prefix='memory-') as temp, ExitStack() as stack:
        db = start(stack, Path(temp) / label, rows, label)
        with LoadMonitor(path) as monitor:
            print('Memory idle gate:', number, label, flush=True)
            result['idle_gate'] = monitor.wait_idle(30, 90, 80, 600)
            stop, errors, stage = threading.Event(), [], ['startup']
            def probe():
                try:
                    while not stop.is_set():
                        result['memory_samples'].append(dict(monotonic_seconds=time.monotonic(), stage=stage[0],
                            cache=stats(db, label), usage=resources(db.pid)))
                        stop.wait(.2)
                except BaseException as e: errors.append(repr(e))
            thread = threading.Thread(target=probe); thread.start()
            try:
                for name, hot_rows in [('broad', rows), ('hot', 20000), ('broad-again', rows)]:
                    stage[0] = name
                    sample = measure(db, queries(hot_rows), ctx, 8)
                    sample.update(cache=stats(db, label), usage=resources(db.pid), stage=name)
                    result['stages'].append(sample)
                    print('Memory stage:', number, label, name, sample['cache'], sample['usage']['rss_bytes'], flush=True)
                cover(monitor, sample['to_monotonic_seconds'])
            finally:
                stop.set(); thread.join(timeout=10)
            assert not thread.is_alive() and not errors, errors
        annotate(result['stages'], path)
        result['thermal_before'], result['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        lifecycle(db, rows)
        result['lifecycle_passed'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck', action='store_true')
    parser.add_argument('--fixtures-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'measurement')
    parser.add_argument('--rows', nargs='+', type=int, default=[20000, 100000, 1000000, 5000000, 20000000])
    parser.add_argument('--duration', type=float, default=5)
    parser.add_argument('--skip-memory', action='store_true')
    parser.add_argument('--scan-only', action='store_true')
    args = parser.parse_args()
    if args.selfcheck:
        assert len(ARMS) == 6 and len(orders(list(ARMS))) == 6
        assert all(sum(order.index(k) == i for order in orders(list(ARMS))) == 1 for k in ARMS for i in range(6))
        for p in queries(20000): assert all(len(q[1]) == 256 for q in p)
        for i in range(8): assert len(list(ScanQueries(10000000, i, 0))) == 16
        print('Final matrix driver selfcheck passed.'); return
    os.environ.update(json.loads((ROOT / 'calibration.json').read_text()))
    for rows in set(args.rows + ([] if args.skip_memory else [5000000])):
        folder = ROOT / 'fixtures' / f'fixture-{rows}'
        if not folder.exists():
            print('Create fixture:', rows, flush=True); make_fixture(str(ROOT / 'searchd'), folder, rows)
    if args.fixtures_only: return
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(source_commit=json.loads((ROOT / 'source-isolation.json').read_text())['commit'],
        binary_sha256=hashlib.sha256((ROOT / 'searchd').read_bytes()).hexdigest(), reader_tls=False,
        docid_cache_bytes=0, query_cache_bytes=0, configurations=ARMS, rounds=6, seconds_per_arm=args.duration,
        planned_rows=args.rows, planned_memory=not args.skip_memory, workload='scan' if args.scan_only else 'random',
        quality_rule='Retain all samples. Mean external CPU >10% machine or peak >20% triggers a complete confirmation, never selective rounds.',
        calibration=json.loads((ROOT / 'calibration.json').read_text()),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), cases=[], memory=[])
    (args.output / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
    ctx = mp.get_context('spawn')
    for number, rows in enumerate(args.rows):
        result['cases'].append(matrix(rows, number, args, ctx, 'scan' if args.scan_only else 'random'))
        (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    if not args.skip_memory:
        for number, labels in [(1, ['manual512', 'adaptive512']), (2, ['adaptive512', 'manual512'])]:
            for label in labels:
                result['memory'].append(transition(number, label, args, ctx))
                (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    result['completed'] = True
    (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__': main()
