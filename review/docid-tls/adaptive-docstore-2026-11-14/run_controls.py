#!/usr/bin/env python3
"""Same-binary A/A control, followed by an advancing-scan capacity comparison."""
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import run_final as bench


def main():
    root = Path(__file__).resolve().parent
    os.environ.update(json.loads((root / 'calibration.json').read_text()))
    ctx = mp.get_context('spawn')
    import argparse
    args = argparse.Namespace(output=root / 'controls', duration=5)
    args.output.mkdir(exist_ok=False)
    data = {'binary_sha256': hashlib.sha256((root / 'searchd').read_bytes()).hexdigest(),
            'benchmark_sha256': hashlib.sha256((root / 'run_final.py').read_bytes()).hexdigest(),
            'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'planned_cases': ['off/off A/A at 20M rows', '20M advancing scan, six capacities/modes'],
            'rounds': 6, 'seconds_per_arm': 5, 'cases': []}
    (args.output / 'plan.json').write_text(json.dumps(data, indent=2) + '\n')
    saved = bench.ARMS
    bench.ARMS = {'off-A': (0, True), 'off-B': (0, True)}
    data['cases'].append(bench.matrix(20000000, 0, args, ctx, 'random'))
    (args.output / 'results.json').write_text(json.dumps(data, indent=2) + '\n')
    bench.ARMS = saved
    data['cases'].append(bench.matrix(20000000, 0, args, ctx, 'scan'))
    data['completed'] = True
    (args.output / 'results.json').write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__': main()
