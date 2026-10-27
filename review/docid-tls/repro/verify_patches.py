#!/usr/bin/env python3
"""Check both independent patches and both application orders using temporary Git indexes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('repository', type=Path)
parser.add_argument('--base', default='047d2f99522d78e0aa1de7e7dc945a9abe1b673a')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
patches = Path(__file__).resolve().parents[1] / 'patches'
result = {'base': args.base, 'patch_sha256': {}, 'application_orders': {}}
for name in ['01-docid-cache.patch', '02-reader-tls.patch']:
    result['patch_sha256'][name] = hashlib.sha256((patches / name).read_bytes()).hexdigest()
for label, order in [('docid-only', ['01-docid-cache.patch']), ('tls-only', ['02-reader-tls.patch']),
                     ('docid-then-tls', ['01-docid-cache.patch', '02-reader-tls.patch']),
                     ('tls-then-docid', ['02-reader-tls.patch', '01-docid-cache.patch'])]:
    with tempfile.TemporaryDirectory(prefix='manticore-review-index-') as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'))
        def git(*command):
            return subprocess.check_output(['git', *command], cwd=args.repository, env=env, text=True)
        git('read-tree', args.base)
        for name in order:
            git('apply', '--cached', '--check', str(patches / name))
            git('apply', '--cached', str(patches / name))
        git('diff', '--cached', '--check')
        result['application_orders'][label] = {'tree': git('write-tree').strip(),
                                               'stat': git('diff', '--cached', '--stat', args.base)}
assert result['application_orders']['docid-then-tls']['tree'] == result['application_orders']['tls-then-docid']['tree']
args.output.write_text(json.dumps(result, indent=2) + '\n')
print('Both patches apply independently and in either order, producing the same combined tree.')
