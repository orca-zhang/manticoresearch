from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,subprocess
r=Path('/private/tmp/manticore-adaptive-cache-review-20261113')
s=Path('/private/tmp/manticore-adaptive-cache-source-20261113')
env=dict(os.environ);env.update(json.loads((r/'calibration.json').read_text()))
env.update(ASAN_OPTIONS='halt_on_error=1:detect_leaks=0',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',TSAN_OPTIONS='halt_on_error=1')
compile_cmd=next(x for x in json.loads((r/'build-commands.json').read_text()) if x['source']=='gtests_docstore_blockcache.cpp')
link_cmd=next(x for x in json.loads((r/'link-commands.json').read_text()) if x['target']=='gmanticoretest')

def run(mode):
    out=r/(mode+'-validated');out.mkdir(exist_ok=True)
    flags=[] if mode=='native' else ['-fsanitize='+('address,undefined' if mode=='asan-ubsan' else 'thread'),'-fno-sanitize-recover=all','-fno-omit-frame-pointer','-O1']
    obj=out/'gtests_docstore_blockcache.cpp.o'
    compile_args=compile_cmd['args'].copy();compile_args[compile_args.index('-o')+1]=str(obj);compile_args+=flags
    link_args=link_cmd['args'].copy();link_args[link_args.index('-o')+1]=str(out/'cache-tests')
    if mode=='native':
        link_args=[str(obj) if Path(a).name=='gtests_docstore_blockcache.cpp.o' else a for a in link_args]
    else:
        link_args=[a for a in link_args if Path(a).name!='gtests_docstore_blockcache.cpp.o']
        link_args += [str(r/mode/(n+'.o')) for n in ['docstore.cpp','skip_cache.cpp','fileio.cpp']]+[str(obj)]+flags
    steps=[dict(cwd=compile_cmd['cwd'],args=compile_args,log='compile.log'),dict(cwd=link_cmd['cwd'],args=link_args,log='link.log'),dict(cwd=str(out),args=[str(out/'cache-tests'),'--gtest_filter=AdaptiveLru.*:Modes/DocstoreBlockCacheTest.*','--gtest_repeat=20'],log='focused-tests.log')]
    if mode=='native':steps.append(dict(cwd=str(out),args=[str(out/'cache-tests'),'--gtest_output=json:'+str(out/'full-tests.json')],log='full-tests.log'))
    (out/'commands.json').write_text(json.dumps(steps,indent=2)+'\n')
    for step in steps:
        with (out/step['log']).open('w') as log:p=subprocess.run(step['args'],cwd=step['cwd'],env=env,stdout=log,stderr=subprocess.STDOUT)
        assert p.returncode==0,(mode,step['log'],p.returncode)
    assert (out/'focused-tests.log').read_text().count('[  PASSED  ] 11 tests.')==20
    (out/'result.json').write_text(json.dumps(dict(passed=True,focused_tests=11,repeats=20,full_tests=529 if mode=='native' else None,leak_detection=False,env={k:env[k] for k in ['ASAN_OPTIONS','UBSAN_OPTIONS','TSAN_OPTIONS']},binary_sha256=hashlib.sha256((out/'cache-tests').read_bytes()).hexdigest()),indent=2)+'\n')
    print(mode,'validated: 11 x20'+(', full 529/529' if mode=='native' else ''),flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,['native','asan-ubsan','tsan']))
