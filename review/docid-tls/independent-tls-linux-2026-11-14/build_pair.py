"""Build an isolated upstream/TLS pair and retain source/object/test evidence."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,traceback
ROOT=Path('/work');E=ROOT/'evidence';LOG=ROOT/'logs';SOURCE=ROOT/'source'
def run(args,name,cwd=ROOT,env=None):
 (ROOT/'stage.txt').write_text(name+'\n')
 with (LOG/(name+'.log')).open('w') as out:
  subprocess.run(args,cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def objects():return {str(p.relative_to(ROOT/'build')):digest(p) for p in sorted((ROOT/'build').rglob('*.o'))}
def test_arm(arm):
 folder=ROOT/('test-'+arm);folder.mkdir()
 env=dict(os.environ,GTEST_DICT=str(SOURCE/'src/gtests'))
 run([str(ROOT/('gtests-'+arm))],arm+'-native',folder,env)
 run([str(ROOT/('gtests-'+arm)),'--gtest_filter=DocstoreReadersTest.*','--gtest_repeat=20'],arm+'-readers',folder,env)
try:
 run(['apt-get','install','-y','--no-install-recommends','libgtest-dev','libgmock-dev'],'gtest-install')
 for name in ['source','bundle','fixtures']:
  run(['tar','-xzf',str(ROOT/(name+'.tar.gz')),'-C',str(ROOT)],'unpack-'+name)
 origin=json.loads((ROOT/'fixture-origin.json').read_text())
 for fixture in (ROOT/'fixtures').glob('fixture-*'):
  for p in (fixture/'data').rglob('*.json'):
   p.write_text(p.read_text().replace(origin['source'],str(ROOT/'fixtures')))
 (E/'fixture-manifest.json').write_text(json.dumps({str(p.relative_to(ROOT/'fixtures')):digest(p) for p in sorted((ROOT/'fixtures').rglob('*')) if p.is_file()},indent=2)+'\n')
 configure=['cmake','-S',str(SOURCE),'-B',str(ROOT/'build'),'-G','Ninja',
 '-DCMAKE_C_COMPILER=clang','-DCMAKE_CXX_COMPILER=clang++','-DCMAKE_BUILD_TYPE=RelWithDebInfo',
 '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O2 -DNDEBUG','-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O2 -DNDEBUG',
 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DBUILD_TESTING=ON','-DWITH_BENCHES=OFF','-DWITH_GALERA=OFF',
 '-DWITH_JIEBA=OFF','-DWITH_MYSQL=OFF','-DWITH_ODBC=OFF','-DWITH_POSTGRESQL=OFF','-DWITH_RE2=OFF',
 '-DWITH_STEMMER=OFF','-DWITH_ICU=ON','-DWITH_ICU_FORCE_STATIC=OFF','-DWITH_SSL=ON','-DMCL_LOCAL_RUNTIME=OFF',
 '-DCACHEB=/work/cache','-DLIBS_BUNDLE=/work/bundle']
 (E/'configure-command.json').write_text(json.dumps(configure,indent=2)+'\n')
 run(configure,'configure')
 build=['cmake','--build',str(ROOT/'build'),'--target','searchd','gmanticoretest','-j3']
 manifest={}
 for arm in ['baseline','tls']:
  if arm=='tls':run(['git','apply',str(ROOT/'tls.patch')],'apply-tls',SOURCE)
  run(build,'build-'+arm)
  for source,target in [('searchd','searchd-'),('gtests/gmanticoretest','gtests-')]:
   shutil.copy2(ROOT/'build/src'/source,ROOT/(target+arm))
  manifest[arm]={'binary_sha256':digest(ROOT/('searchd-'+arm)),'objects':objects()}
  (E/('objects-'+arm+'.json')).write_text(json.dumps(manifest[arm],indent=2)+'\n')
  test_arm(arm)
 changed=[p for p,h in manifest['baseline']['objects'].items() if manifest['tls']['objects'].get(p)!=h]
 assert changed==['src/CMakeFiles/lmanticore.dir/docstore.cpp.o'],changed
 (E/'changed-objects.json').write_text(json.dumps({'count':len(manifest['baseline']['objects']),'changed':changed},indent=2)+'\n')
 shutil.copy2(ROOT/'build/compile_commands.json',E/'compile_commands.json')
 shutil.copy2(ROOT/'build/CMakeCache.txt',E/'CMakeCache.txt')
 run(['git','diff','--','src/docstore.cpp'],'production-diff',SOURCE)
 run(['clang++','--version'],'compiler')
 run(['dpkg-query','-W'],'packages')
 run(['python3','/work/driver/run_tls.py','--selfcheck'],'driver-selfcheck')
 run(['python3','/work/driver/load_telemetry.py'],'telemetry-selfcheck')
 (ROOT/'stage.txt').write_text('BUILD_PAIR_COMPLETE\n')
except BaseException:
 (ROOT/'failure.txt').write_text(traceback.format_exc());raise
