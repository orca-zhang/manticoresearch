"""Run once after the controlled pair has built; preserve complete repeats."""
from pathlib import Path
from contextlib import ExitStack
import json,os,subprocess,sys,tempfile,time,traceback
ROOT=Path('/work');sys.path.insert(0,str(ROOT/'driver'))
import benchmark,run_tls

def stage(s):
 (ROOT/'experiment-stage.txt').write_text(s+'\n');print(s,flush=True)
def run(args,log):
 with (ROOT/'logs'/log).open('w') as out:subprocess.run(args,check=True,stdout=out,stderr=subprocess.STDOUT)
try:
 stage('Waiting for the build and native tests')
 while (ROOT/'stage.txt').read_text().strip()!='BUILD_PAIR_COMPLETE':
  if (ROOT/'failure.txt').exists():raise RuntimeError((ROOT/'failure.txt').read_text())
  time.sleep(2)
 stage('Fixture smoke checks')
 smoke=[]
 for rows in [20000,1000000,10000000]:
  fixture=ROOT/'fixtures'/f'fixture-{rows}'
  for arm in ['baseline','tls']:
   with tempfile.TemporaryDirectory(prefix='smoke-',dir=ROOT) as temp:
    folder=Path(temp);run_tls.clone_data(fixture,folder)
    with benchmark.ReaderServer(str(ROOT/('searchd-'+arm)),folder,16*2**20).running() as db:
     assert db.sql('SELECT count(*) AS n FROM docs')['data']==[{'n':rows}]
     for i in [1,rows//2,rows]:assert db.sql(f'SELECT id,body FROM docs WHERE id={i}')['data']==[{'id':i,'body':benchmark.value(i)}]
     smoke.append({'rows':rows,'arm':arm,'passed':True,'status':db.sql('SHOW STATUS')['data']})
 (ROOT/'evidence/fixture-smoke.json').write_text(json.dumps(smoke,indent=2)+'\n')
 stage('Measuring 23 cases, 6 balanced rounds per case')
 command=['python3','/work/driver/run_tls.py','--fixtures','/work/fixtures','--rounds','6','--duration','5']
 run(command+['--output','/work/measurement'],'measurement.log')
 data=json.loads((ROOT/'measurement/results.json').read_text())
 affected=[x['case']['name'] for x in data['cases'] if any(s['quality_flag'] for a in x['arms'].values() for s in a['samples'])]
 (ROOT/'evidence/repeat-policy-decision.json').write_text(json.dumps({'policy':'Repeat every flagged comparison in full once; retain originals and repeats; do not select by QPS','affected_cases':affected},indent=2)+'\n')
 if affected:
  stage('Repeating all flagged comparisons in full: '+', '.join(affected))
  run(command+['--output','/work/repeat','--cases']+affected,'repeat.log')
 stage('EXPERIMENT_COMPLETE')
except BaseException:
 (ROOT/'experiment-failure.txt').write_text(traceback.format_exc());raise
