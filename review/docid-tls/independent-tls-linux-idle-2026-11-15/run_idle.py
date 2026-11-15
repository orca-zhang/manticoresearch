"""Run complete strict-idle pairs; preserve all originals, errors and repeats."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,time,traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'driver'))
from run_tls import cases

def status(stage,**extra):
 (ROOT/'status.json').write_text(json.dumps({'stage':stage,'unix_seconds':time.time(),**extra},indent=2)+'\n')
def run(script,folder,names):
 cmd=[sys.executable,str(ROOT/'driver'/script),'--fixtures','/work/fixtures','--output',str(ROOT/folder),'--rounds','6','--duration','5','--cases',*names]
 status('running',phase=folder,cases=names)
 with (ROOT/'logs'/(folder+'.log')).open('w') as log:
  subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
 return json.loads((ROOT/folder/'results.json').read_text())

def merge(datasets):
 selected={row['case']['name']:(row,phase) for phase,data in datasets for row in data['cases']}
 assert len(selected)==23
 result=dict(datasets[0][1],cases=[],planned_cases=cases(),completed=True,
  source_phases={phase:{'driver_sha256':data['driver_sha256'],'transport':data.get('transport','Original CPython HTTP')} for phase,data in datasets})
 out=ROOT/'merged';out.mkdir(exist_ok=False)
 for case in cases():
  row,phase=selected[case['name']];assert row['case']==case
  assert all(data['binary_sha256']==result['binary_sha256'] for _,data in datasets)
  result['cases'].append(dict(row,source_phase=phase,driver_sha256=result['source_phases'][phase]['driver_sha256']))
  for ending in ['-samples.jsonl','-load.jsonl']:shutil.copy2(ROOT/phase/(case['name']+ending),out/(case['name']+ending))
 (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
 return result

if __name__=='__main__':
 try:
  matrix=cases();low=[c['name'] for c in matrix if c['clients']!=32];high=[c['name'] for c in matrix if c['clients']==32]
  assert len(low)==19 and len(high)==4
  first=run('run_tls.py','measurement',low)
  second=run('run_coalesced32.py','coalesced32',high)
  data=merge([('measurement',first),('coalesced32',second)])
  flagged=[r['case']['name'] for r in data['cases'] if any(s['quality_flag'] for a in r['arms'].values() for s in a['samples'])]
  repeats=[]
  for suffix,script,names in [('low','run_tls.py',[n for n in flagged if n in low]),('high','run_coalesced32.py',[n for n in flagged if n in high])]:
   if names:repeats.append(('repeat-'+suffix,run(script,'repeat-'+suffix,names)))
  # A/A uses a separate binary root and the unchanged original transport driver.
  aaroot=ROOT/'aa32';aaroot.mkdir();shutil.copytree(ROOT/'driver',aaroot/'driver',ignore=shutil.ignore_patterns('__pycache__'))
  for label in ['baseline','tls']:(aaroot/('searchd-'+label)).symlink_to(ROOT/'searchd-baseline')
  diagnostics=[]
  for cache in [16,0]:
   name=f'churn-c32-20000-{cache}m'
   for is_aa in [False,True]:
    folder=('aa32-' if is_aa else 'original32-')+str(cache)+'m'
    script=(aaroot if is_aa else ROOT)/'driver/run_tls.py'
    status('running',phase=folder,cases=[name])
    cmd=[sys.executable,str(script),'--fixtures','/work/fixtures','--output',str(ROOT/folder),'--rounds','6','--duration','5','--cases',name]
    with (ROOT/'logs'/(folder+'.log')).open('w') as log:
     proc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    diagnostics.append({'phase':folder,'same_upstream_binary_both_arms':is_aa,'returncode':proc.returncode})
  (ROOT/'diagnostic-status.json').write_text(json.dumps(diagnostics,indent=2)+'\n')
  status('complete',primary_cases=23,primary_samples=276,flagged_primary_cases=flagged,repeat_phases=[x for x,_ in repeats],diagnostics=diagnostics)
 except BaseException:
  status('failed',traceback=traceback.format_exc());raise
