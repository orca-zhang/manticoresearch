import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

root = Path(__file__).parent
build = Path('/private/tmp/manticore-admission-review-20261114/build')
commands = json.loads((build / 'compile_commands.json').read_text())
env = dict(os.environ, **json.loads(Path('/private/tmp/manticore-admission-review-20261114/calibration.json').read_text()))
focus = '*DocstoreBlockCache*:*DocstoreBlockPool*:*AdaptiveLru*:*DocstoreAdmission*'
for label, sanitizer in [('asan-ubsan', 'address,undefined'), ('tsan', 'thread')]:
    folder = root / label
    folder.mkdir(exist_ok=True)
    with (folder / 'build.log').open('w') as log:
        for name in ['docstore.cpp', 'fileio.cpp', 'gtests_docstore_blockcache.cpp']:
            entry = next(c for c in commands if Path(c['file']).name == name)
            args = shlex.split(entry['command'])
            args[args.index('-o') + 1] = str(folder / (name + '.o'))
            args += ['-O1', '-g', '-fsanitize=' + sanitizer, '-fno-omit-frame-pointer']
            subprocess.run(args, cwd=entry['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['/bin/cp', '-c', str(build / 'src/liblmanticore.a'), str(folder / 'liblmanticore.a')], check=True)
        subprocess.run(['ar', '-r', str(folder / 'liblmanticore.a'), str(folder / 'docstore.cpp.o'), str(folder / 'fileio.cpp.o')], check=True, stdout=log, stderr=subprocess.STDOUT)
        args = shlex.split((build / 'src/gtests/CMakeFiles/gmanticoretest.dir/link.txt').read_text())
        args[args.index('-o') + 1] = str(folder / 'tests')
        args = [str(folder / 'liblmanticore.a') if x.endswith('liblmanticore.a') else
                str(folder / 'gtests_docstore_blockcache.cpp.o') if x.endswith('gtests_docstore_blockcache.cpp.o') else x for x in args]
        args += ['-fsanitize=' + sanitizer]
        subprocess.run(args, cwd=build / 'src/gtests', stdout=log, stderr=subprocess.STDOUT, check=True)
    test_env = dict(env, ASAN_OPTIONS='detect_leaks=0:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1', TSAN_OPTIONS='halt_on_error=1')
    with (folder / 'tests.log').open('w') as output:
        result = subprocess.run([str(folder / 'tests'), '--gtest_filter=' + focus, '--gtest_repeat=20', '--gtest_break_on_failure'], cwd=folder, env=test_env, stdout=output, stderr=subprocess.STDOUT)
    print(label, 'exit', result.returncode, flush=True)
    if result.returncode:
        print((folder / 'tests.log').read_text()[-8000:], flush=True)
        raise SystemExit(result.returncode)
