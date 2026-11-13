#!/usr/bin/env python3
"""Independent #5045 experiment: original upstream block cache in both arms."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import tempfile
import time
import urllib.parse

import benchmark
from benchmark import ReaderServer, queries_for
from load_telemetry import LoadMonitor
from support import resources

ROOT = Path(__file__).resolve().parent.parent


def cases():
    matrix = []
    def add(name, rows, cache, batch=256, **extra):
        matrix.append(dict(name=name, rows=rows, cache_mib=cache, batch=batch,
                           clients=8, **extra))
    for rows in (20000, 1000000, 10000000):
        for cache in (16, 0):
            add(f'random256-{rows}-{cache}m', rows, cache)
    for rows in (20000, 1000000):
        for cache in (16, 0):
            add(f'random64-{rows}-{cache}m', rows, cache, 64)
    for cache in (16, 0):
        add(f'point-20000-{cache}m', 20000, cache, 1)
        add(f'mixed-1000000-{cache}m', 1000000, cache, mixed=True)
    add('count-1000000-16m', 1000000, 16, count=True)
    for cache in (16, 0):
        add(f'aa-20000-{cache}m', 20000, cache, aa=True)
    return matrix


def pools_for(case):
    pools = []
    for worker in range(case['clients']):
        point = case.get('mixed') and worker >= 4
        pools.append(queries_for(case['rows'], 1 if point else case['batch'], worker,
                                 count=case.get('count', False), hot=bool(point))[:128])
    return pools


def clone_data(source, target):
    subprocess.run(['/bin/cp', '-cR', str(source / 'data'), str(target / 'data')], check=True)
    for file in (target / 'data').rglob('*.json'):
        file.write_text(file.read_text().replace(str(source / 'data'), str(target / 'data')))


def measure(db, pools, pool, go, ready, duration):
    go.clear()
    jobs = [pool.apply_async(benchmark.worker, (db.port, queries, duration, False, None))
            for queries in pools]
    for _ in jobs:
        assert ready.get(timeout=180) is True
    before = resources(db.pid)
    stamp = time.monotonic()
    started = time.perf_counter()
    go.set()
    replies = [job.get(timeout=duration + 30) for job in jobs]
    ended = time.monotonic()
    after = resources(db.pid)
    elapsed = max(r['finished'] for r in replies) - started
    completed = sum(r['completed'] for r in replies)
    latency = [v for reply in replies for v in reply['latencies_ns']]
    return dict(completed=completed, elapsed_seconds=elapsed, qps=completed / elapsed,
                server_cpu_ms_per_query=(after['cpu_ns'] - before['cpu_ns']) / 1e6 / completed,
                rss_bytes=after['rss_bytes'], p95_ms=benchmark.quantile(latency, .95) / 1e6,
                client_cpu_cores=sum(r['client_cpu_ns'] for r in replies) / 1e9 / elapsed,
                bulk_qps=sum(r['completed'] for r in replies[:4]) / elapsed,
                point_qps=sum(r['completed'] for r in replies[4:]) / elapsed,
                from_monotonic_seconds=stamp, to_monotonic_seconds=ended)


def cover_final(monitor, ended):
    deadline = time.monotonic() + 10
    while not monitor.samples or monitor.samples[-1]['monotonic_seconds'] < ended:
        if monitor.error:
            raise monitor.error
        assert time.monotonic() < deadline
        time.sleep(.05)


def annotate(entry, telemetry):
    for arm in entry['arms'].values():
        for sample in arm['samples']:
            overlap = [x for x in telemetry
                       if x['monotonic_seconds'] >= sample['from_monotonic_seconds']
                       and x['monotonic_seconds'] - x['interval_seconds'] <= sample['to_monotonic_seconds']]
            assert overlap
            sample['external_cpu_mean_machine_percent'] = statistics.mean(x['external_cpu_percent_machine'] for x in overlap)
            sample['external_cpu_peak_machine_percent'] = max(x['external_cpu_percent_machine'] for x in overlap)
            sample['quality_flag'] = (sample['external_cpu_mean_machine_percent'] > 10 or
                                      sample['external_cpu_peak_machine_percent'] > 20)
        for metric in ('qps', 'server_cpu_ms_per_query', 'p95_ms', 'rss_bytes', 'bulk_qps', 'point_qps'):
            arm[metric + '_median'] = statistics.median(s[metric] for s in arm['samples'])
    a, b = (entry['arms'][x] for x in ('baseline', 'tls'))
    entry['qps_change_percent'] = (b['qps_median'] / a['qps_median'] - 1) * 100
    entry['cpu_change_percent'] = (b['server_cpu_ms_per_query_median'] / a['server_cpu_ms_per_query_median'] - 1) * 100
    entry['paired_qps_changes_percent'] = [(y['qps'] / x['qps'] - 1) * 100 for x, y in zip(a['samples'], b['samples'])]
    entry['paired_cpu_changes_percent'] = [(y['server_cpu_ms_per_query'] / x['server_cpu_ms_per_query'] - 1) * 100
                                          for x, y in zip(a['samples'], b['samples'])]


def lifecycle(db, rows):
    db.sql("REPLACE INTO docs (id,body) VALUES (7,'replacement')")
    db.sql('FLUSH RAMCHUNK docs')
    assert db.sql('SELECT body FROM docs WHERE id=7')['data'] == [{'body': 'replacement'}]
    assert db.sql('SELECT count(*) AS n FROM docs')['data'] == [{'n': rows}]
    db.sql('DROP TABLE docs')
    db.sql('CREATE TABLE docs (body text stored)')
    db.sql("INSERT INTO docs (id,body) VALUES (7,'new table')")
    db.sql('FLUSH RAMCHUNK docs')
    assert db.sql('SELECT body FROM docs WHERE id=7')['data'] == [{'body': 'new table'}]


def run_case(case, number, args):
    pools = pools_for(case)
    entry = {'case': case, 'arms': {}, 'query_pool_sizes': [len(q) for q in pools],
             'query_sha256': hashlib.sha256(b'\n'.join(q[0] for p in pools for q in p)).hexdigest()}
    fixture = args.fixtures / f"fixture-{case['rows']}"
    assert fixture.is_dir(), fixture
    entry['fixture'] = {'spds_bytes': sum(p.stat().st_size for p in (fixture / 'data').rglob('*.spds')),
                        'disk_chunks': len(list((fixture / 'data').rglob('*.spds'))),
                        'logical_text_bytes': case['rows'] * 128}
    journal = args.output / (case['name'] + '-samples.jsonl')
    assert not journal.exists()
    ctx = mp.get_context('spawn')
    with tempfile.TemporaryDirectory(prefix='servers-', dir=ROOT) as temp, ExitStack() as stack:
        servers = {}
        labels = ['baseline', 'tls'] if number % 2 == 0 else ['tls', 'baseline']
        for label in labels:
            folder = Path(temp) / label
            folder.mkdir()
            clone_data(fixture, folder)
            binary = 'searchd-baseline' if case.get('aa') or label == 'baseline' else 'searchd-tls'
            db = ReaderServer(str(ROOT / binary), folder, case['cache_mib'] * 2**20)
            config = db.config.read_text()
            assert 'docid_lookup_cache' not in config and 'adaptive' not in config
            servers[label] = stack.enter_context(db.running())
            sql = urllib.parse.parse_qs(pools[0][0][0].decode())['query'][0]
            entry['arms'][label] = {'binary': binary, 'samples': [], 'config': config,
                                   'meta': db.sql_all(sql + '; SHOW META')[1]['data']}
        load_path = args.output / (case['name'] + '-load.jsonl')
        with LoadMonitor(load_path) as monitor:
            print('Idle gate:', case['name'], flush=True)
            entry['idle_gate'] = monitor.wait_idle(30, 90, 80, 600)
            go, ready = ctx.Event(), ctx.Queue()
            with ctx.Pool(8, initializer=benchmark.init_worker, initargs=(go, ready)) as pool:
                for repeat in range(args.rounds):
                    order = labels if repeat % 2 == 0 else labels[::-1]
                    for label in order:
                        sample = measure(servers[label], pools, pool, go, ready, args.duration)
                        sample.update(round=repeat, order=order)
                        entry['arms'][label]['samples'].append(sample)
                        with journal.open('a') as file:
                            file.write(json.dumps({'arm': label, 'sample': sample}) + '\n')
                    print('Round', repeat + 1, case['name'], flush=True)
            cover_final(monitor, sample['to_monotonic_seconds'])
        entry['thermal_before'], entry['thermal_after'] = monitor.thermal_before, monitor.thermal_after
        annotate(entry, [json.loads(line) for line in load_path.read_text().splitlines()])
        for db in servers.values():
            lifecycle(db, case['rows'])
        entry['lifecycle_passed'] = True
    print('RESULT', case['name'], 'QPS', round(entry['qps_change_percent'], 2),
          'CPU/query', round(entry['cpu_change_percent'], 2), flush=True)
    return entry


def selfcheck():
    matrix = cases()
    assert len(matrix) == len({x['name'] for x in matrix}) == 17
    for case in matrix:
        pools = pools_for(case)
        assert len(pools) == 8
        for index, pool in enumerate(pools):
            batch = 1 if case.get('mixed') and index >= 4 else case['batch']
            assert all(len(expected) == (1 if case.get('count') else batch) for _, expected in pool)
    assert pools_for(matrix[0]) == pools_for(matrix[0])
    assert all((n % 2) != ((n + 1) % 2) for n in range(5))
    print('TLS driver selfcheck passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck', action='store_true')
    parser.add_argument('--fixtures', type=Path, default=Path('/private/tmp/manticore-admission-review-20261114/fixtures'))
    parser.add_argument('--output', type=Path, default=ROOT / 'measurement')
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--duration', type=float, default=5)
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.rounds >= 2 and args.rounds % 2 == 0 and args.duration > 0
    matrix = [x for x in cases() if not args.cases or x['name'] in args.cases]
    assert matrix and (not args.cases or len(matrix) == len(args.cases))
    os.environ.update(json.loads((ROOT / 'calibration.json').read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'comparison': 'Upstream 047d2f9 vs PR #5045 TLS only; original upstream single-lock block cache in BOTH arms',
              'upstream_base': '047d2f99522d78e0aa1de7e7dc945a9abe1b673a',
              'tls_pr_head': '019868e9f79d1bb2bd1f96dafb88ef20acd45418',
              'platform': platform.platform(), 'rounds': args.rounds, 'seconds_per_arm': args.duration,
              'payload_bytes': 128, 'block_bytes': 16384, 'compression': 'lz4',
              'query_cache_bytes': 0, 'reader_buffer_budget_bytes': 8388608,
              'docid_cache': 'Upstream has no native DocID cache; no setting injected',
              'planned_cases': matrix, 'calibration': json.loads((ROOT / 'calibration.json').read_text()),
              'binary_sha256': {x: hashlib.sha256((ROOT / ('searchd-' + x)).read_bytes()).hexdigest() for x in ('baseline', 'tls')},
              'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'quality_policy': 'Retain every sample; flag external mean CPU >10% machine or one-second peak >20%; repeat affected comparisons in full, never select rounds by QPS',
              'cases': []}
    (args.output / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
    for number, case in enumerate(matrix):
        result['cases'].append(run_case(case, number, args))
        (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    result['completed'] = True
    (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
