#!/usr/bin/env python3
"""Preserve a portable evidence snapshot; omit executable binaries and large fixtures."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

root=Path(__file__).resolve().parent
durable=Path('/Users/orca/Documents/manticore-benchmarks/adaptive-docstore-pr-20261114')
docs=Path('/private/tmp/manticore-tls-evidence-20261114/review/docid-tls')
source=Path('/private/tmp/manticore-admission-source-20261114')
assert json.loads((root/'controls/results.json').read_text())['completed']
assert 'Final local build/checks and English evidence complete' in (root/'finish-local.log').read_text()
durable.mkdir(parents=True,exist_ok=True)
for p in (root/'report').iterdir():
    if p.is_file():shutil.copy2(p,durable/p.name)
for name in ('run_final.py','run_controls.py','summarize.py','write_docs.py','check_sanitizers.py',
             'run_pending.py','finish_local.py','package.py','source.patch','full-pr.patch',
             'source-isolation.json','publish-identity.json','calibration.json','build-settings.json'):
    shutil.copy2(root/name,durable/name)
shutil.copytree(root/'driver',durable/'driver',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
raw=durable/'raw';raw.mkdir(exist_ok=True)
for folder in [root/'measurement',*sorted(root.glob('confirm-*')),root/'controls']:
    if folder.is_dir():shutil.copytree(folder,raw/folder.name,dirs_exist_ok=True)
validation=durable/'validation';validation.mkdir(exist_ok=True)
for p in root.iterdir():
    if p.is_file() and (p.suffix=='.log' or p.name.startswith('ci-') or p.name=='binary-publish-version.txt'):
        shutil.copy2(p,validation/p.name)
for name in ('asan-ubsan','tsan'):
    target=validation/name;target.mkdir(exist_ok=True)
    for p in (root/name).glob('*.log'):shutil.copy2(p,target/p.name)
identity=json.loads((root/'source-isolation.json').read_text())
for name,expected in identity['source_sha256'].items():
    assert hashlib.sha256((source/name).read_bytes()).hexdigest()==expected,name
settings=json.loads((root/'build-settings.json').read_text())
flags=[f'-D{k}={v}' for k,v in settings.items() if k.startswith('WITH_') or k in ('BUILD_TESTING','CMAKE_BUILD_TYPE','CMAKE_CXX_FLAGS_RELWITHDEBINFO','CMAKE_C_FLAGS_RELWITHDEBINFO')]
repro='''# Reproduction

The measured cache implementation is `8fec92b21c2f10f720f0bcbca498c5f8179f7ac0`.
Published head `90e884162544cc36d06fe3f20a978c6817c0e354` differs only by moving
three CMake test-source registrations; `publish-identity.json` records this.
The original implementation and the publication follow-up are tested separately.
The complete source patch is relative to upstream `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`.

## Build and checks

Use the repository's documented dependencies and Apple Clang 21 on macOS.
`build-settings.json` records compiler paths, options, flags and generator;
`validation/configure.log` records dependency/configuration output. The main
CMake arguments are also recorded as an array in `configure-arguments.json`
so spaces in optimization flags remain unambiguous. Build `searchd` and
`gmanticoretest`. Run the native executable with `GTEST_DICT` pointing to
the checkout's `src/gtests`, and the API smoke test with:

```sh
ctest --test-dir build -R 'Perform API smoke test' --output-on-failure
python3 test/docid-cache/test_integration.py build/src/searchd
```

`check_sanitizers.py` retains the focused ASan+UBSan and TSan build/run commands.
It reuses this run's build/dependency paths; adjust the source/build constants
for a new checkout. The recorded sanitizer scope is not a fully instrumented engine.

## Fresh measurements

Place the measured build's executable at `./searchd`, beside `run_final.py`.
These standard-library benchmark drivers use macOS Mach CPU/memory telemetry.
Large immutable data fixtures are generated on first run; they and executable
binaries are intentionally omitted. Keep adequate disk space for the 20M-row
fixture and APFS clones. Do not run the following commands concurrently:

```sh
python3 run_final.py --selfcheck
python3 run_final.py
python3 run_controls.py
```

The first command checks query sizes and balanced ordering. The matrix records
the exact script/binary hashes and each arm's config before timing. It checks
every timed response and exercises REPLACE/flush/drop/recreate afterward.
DocID and SQL query caches are zero. Original outputs are in `raw/` and will
not be overwritten by the default fresh-run output directories.

The original 100k-row case triggered the pre-recorded complete-repeat rule.
Its full confirmation command was:

```sh
python3 run_final.py --rows 100000 --skip-memory --output confirm-100000
```

Both complete series are preserved; no individual round was removed. The
memory diagnostics have two passes with reversed manual/adaptive order;
the second manual pass also provides an independent repetition of the first.
Memory-sampler throughput is not pooled into the primary QPS tables.

## Regenerate the preserved tables and figures

Use a Python environment with Matplotlib:

```sh
python3 summarize.py raw regenerated
python3 write_docs.py . regenerated
```

`summarize.py` asserts journal/result equality, six samples per arm, median
arithmetic, shared binary identity and completed lifecycle checks. The archive's
`MANIFEST.json` gives a SHA-256 for every file except itself.
'''
(durable/'REPRODUCE.md').write_text(repro)
(durable/'configure-arguments.json').write_text(json.dumps(flags,indent=2)+'\n')
submodules=subprocess.check_output(['git','submodule','status'],cwd=source,text=True)
(durable/'submodules.txt').write_text(submodules)
files={str(p.relative_to(durable)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(durable.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
(durable/'MANIFEST.json').write_text(json.dumps(dict(measured_commit=identity['commit'],files_sha256=files),indent=2)+'\n')
target=docs/'adaptive-docstore-2026-11-14'
shutil.copytree(durable,target,dirs_exist_ok=True)
attachment=docs/'attachments/adaptive-docstore-final-20261114.zip'
with zipfile.ZipFile(attachment,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(durable.rglob('*')):
        if p.is_file():z.write(p,arcname=str(p.relative_to(durable)))
with zipfile.ZipFile(attachment) as z:
    assert z.testzip() is None
    for name,digest in files.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
digest=hashlib.sha256(attachment.read_bytes()).hexdigest()
shutil.copy2(attachment,durable.parent/attachment.name)
(durable.parent/(attachment.name+'.sha256')).write_text(digest+'  '+attachment.name+'\n')
print(json.dumps(dict(files=len(files)+1,archive_sha256=digest,archive_bytes=attachment.stat().st_size,durable=str(durable)),indent=2))
