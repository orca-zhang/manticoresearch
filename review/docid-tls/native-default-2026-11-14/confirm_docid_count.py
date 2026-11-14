#!/usr/bin/env python3
"""Fresh-process count control, reversed startup order and explicit-size arm."""
from contextlib import ExitStack
import hashlib
import itertools
import json
import multiprocessing as mp
import os
from pathlib import Path
import statistics
import subprocess
import tempfile

import run_final as bench
from test_docid_independent import pools
from test_docid_default import BINARY, COMMIT, used

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'docid-count-confirmation-20261114'


def main():
    os.environ.update(json.loads((ROOT / 'calibration.json').read_text()))
    version = subprocess.check_output([str(BINARY), '--version'], text=True)
    assert COMMIT in version
    OUT.mkdir(exist_ok=False)
    startup = [('default', None), ('off', 0), ('explicit64', 64 * 2**20)]
    orders = list(itertools.permutations(label for label, _ in startup))
    result = dict(version=version, binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  rows=1000000, workload='full-count', clients=8, seconds_per_arm=5,
                  rounds=6, orders=orders, startup_order=[s[0] for s in startup], arms={})
    (OUT / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
    ctx = mp.get_context('spawn')
    queries = pools(1000000, 'full-count')
    with tempfile.TemporaryDirectory(dir=ROOT, prefix='docid-count-') as temp, ExitStack() as stack:
        servers = {}
        for label, budget in startup:
            folder = Path(temp) / label
            folder.mkdir()
            bench.clone(ROOT / 'fixtures/fixture-1000000', folder)
            server = bench.ReaderServer(str(BINARY), folder, 16 * 2**20, docid_cache=budget)
            server.config.write_text(server.config.read_text().replace('buddy_path =', 'docstore_cache = 1\nbuddy_path ='))
            servers[label] = stack.enter_context(server.running())
            assert used(servers[label]) == 0
            result['arms'][label] = dict(config=server.config.read_text(), samples=[])
        path = OUT / 'load.jsonl'
        with bench.LoadMonitor(path) as monitor:
            print('Idle gate: count confirmation', flush=True)
            result['idle_gate'] = monitor.wait_idle(30, 90, 80, 300)
            for repeat, order in enumerate(orders):
                for label in order:
                    db = servers[label]
                    sample = bench.measure(db, queries, ctx, 5)
                    sample.update(round=repeat, order=order, docid_used_bytes=used(db))
                    assert sample['docid_used_bytes'] == 0
                    result['arms'][label]['samples'].append(sample)
                    with (OUT / 'samples.jsonl').open('a') as f:
                        f.write(json.dumps(dict(arm=label, sample=sample)) + '\n')
                print('Round', repeat + 1, flush=True)
            bench.cover(monitor, sample['to_monotonic_seconds'])
        for arm in result['arms'].values():
            bench.annotate(arm['samples'], path)
            for key in ('qps', 'cpu_ms_per_query'):
                arm[key] = statistics.median(s[key] for s in arm['samples'])
        result.update(completed=True, thermal_before=monitor.thermal_before, thermal_after=monitor.thermal_after)
        (OUT / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
        for label, arm in result['arms'].items():
            print(label, arm['qps'], arm['cpu_ms_per_query'], flush=True)
        print('Quality flags:', sum(s['quality_flag'] for a in result['arms'].values() for s in a['samples']), flush=True)


if __name__ == '__main__':
    main()
