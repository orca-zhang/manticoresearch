from pathlib import Path
import json,os,shlex,subprocess,sys

kind=sys.argv[1]
assert kind in ['address,undefined','thread']
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
b=Path('/private/tmp/manticore-5042-publish-build-20261113')
s=Path('/private/tmp/manticore-vm-cache-source-20261113')
out=r/('asan-ubsan' if kind=='address,undefined' else 'tsan');out.mkdir(exist_ok=True)
database=json.loads((b/'compile_commands.json').read_text())
flags=['-fsanitize='+kind,'-fno-sanitize-recover=all','-fno-omit-frame-pointer','-O1']
commands=[];objects=[]
for name in ['docstore.cpp','skip_cache.cpp','fileio.cpp','gtests_docstore_blockcache.cpp']:
    entry=next(e for e in database if Path(e['file']).name==name)
    args=[a.replace('/private/tmp/manticore-5042-cache-publish-20261113',str(s)).replace(str(s/'mcl'),'/private/tmp/manticore-5042-cache-publish-20261113/mcl') for a in shlex.split(entry['command'])]
    obj=out/(name+'.o');args[args.index('-o')+1]=str(obj);args+=flags
    commands.append(dict(cwd=entry['directory'],args=args))
    with (out/(name+'-compile.log')).open('w') as log:subprocess.run(args,cwd=entry['directory'],stdout=log,stderr=subprocess.STDOUT,check=True)
    objects.append(str(obj));print(kind,'compiled',name,flush=True)
link=next(e for e in json.loads((r/'link-commands.json').read_text()) if e['target']=='gmanticoretest')
args=[a for a in link['args'] if Path(a).name!='gtests_docstore_blockcache.cpp.o']
args[args.index('-o')+1]=str(out/'cache-tests');args+=objects+flags
commands.append(dict(cwd=link['cwd'],args=args))
with (out/'link.log').open('w') as log:subprocess.run(args,cwd=link['cwd'],stdout=log,stderr=subprocess.STDOUT,check=True)
env=dict(os.environ);env.update(json.loads((r/'calibration.json').read_text()))
env.update(ASAN_OPTIONS='halt_on_error=1:detect_leaks=0',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',TSAN_OPTIONS='halt_on_error=1')
test=[str(out/'cache-tests'),'--gtest_filter=DocstoreBlockPool.*:AdaptiveLru.*:Modes/DocstoreBlockCacheTest.*','--gtest_repeat=20']
commands.append(dict(cwd=str(out),args=test))
(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
with (out/'tests.log').open('w') as log:result=subprocess.run(test,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT)
assert result.returncode==0,(kind,result.returncode)
assert (out/'tests.log').read_text().count('[  PASSED  ] 19 tests.')==20
print(kind,'passed 19 tests x20; fail-fast sanitizer checks.',flush=True)
