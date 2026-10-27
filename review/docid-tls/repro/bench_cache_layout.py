#!/usr/bin/env python3
"""Compare fixed-16 and adaptive directory widths with stack scratch in both arms.

Standalone C++17 lookup throughput, not SQL QPS. Matching source/header pairs
are saved with the experiment. Compiler flags and source hashes are recorded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, help='optional directory with current docidlookupcache.h/.cpp')
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--opt-level', choices=[2, 3], type=int, default=3)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    assert args.rounds > 0
    here = Path(__file__).resolve().parent
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    compiler = shlex.split(os.environ.get('CXX', 'c++'))
    manifest = {'compiler': subprocess.check_output(compiler + ['--version'], text=True).splitlines()[0],
                'rounds': args.rounds, 'opt_level': args.opt_level, 'tile_size': 16,
                'metric': 'thread CPU ns/lookup; gain = median(fixed16)/median(adaptive)-1',
                'sources': {}, 'commands': []}
    for label in ['fixed16', 'adaptive']:
        source = args.candidate if label == 'adaptive' and args.candidate else here / 'cache-layout-sources' / label
        folder = args.output / label
        folder.mkdir(exist_ok=True)
        manifest['sources'][label] = {}
        for name in ['docidlookupcache.h', 'docidlookupcache.cpp']:
            shutil.copy2(source / name, folder / name)
            manifest['sources'][label][name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        probe = (here / 'probe_cache_layout.cpp').read_text().replace(
            'pCache->FindBatch ( dQueries.data(), dRows.data(), dQueries.size() );',
            'for ( size_t i=0; i<dQueries.size(); i+=16 )\n'
            '\t\t\t\t\t\t\tpCache->FindBatch ( dQueries.data()+i, dRows.data()+i, std::min(size_t(16),dQueries.size()-i) );')
        (folder / 'probe.cpp').write_text(probe)
        command = compiler + ['-std=c++17', f'-O{args.opt_level}', '-Wall', '-Wextra', '-Werror',
                              '-fstack-usage', '-DDOCID_BATCH_PROBE', '-I', str(folder),
                              str(folder / 'probe.cpp'), str(folder / 'docidlookupcache.cpp'),
                              '-o', str(folder / 'probe')]
        manifest['commands'].append(command)
        subprocess.run(command, check=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.compile_only:
        return
    for order, count in [('sorted', 1000), ('random', 131072)]:
        with (args.output / f'{order}.csv').open('w') as output:
            output.write('variant,documents,miss_percent,mode,sample,cpu_ns_per_lookup,cache_bytes\n')
            output.flush()
            for repeat in range(args.rounds):
                labels = ['fixed16', 'adaptive'] if repeat % 2 == 0 else ['adaptive', 'fixed16']
                for label in labels:
                    subprocess.run([str(args.output / label / 'probe'), label, order, str(count)]
                                   + (['reverse'] if repeat % 2 else []), stdout=output, check=True)


if __name__ == '__main__':
    main()
