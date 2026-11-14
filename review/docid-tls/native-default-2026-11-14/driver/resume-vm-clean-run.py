from pathlib import Path
import hashlib,json,multiprocessing as mp,os,shutil,subprocess,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
sys.path.insert(0,str(r/'driver'))
import vm_cache

def main():
 output=r/'idle-repeat';p=output/'matrix.json';data=json.loads(p.read_text())
 assert [c['rows'] for c in data['cases']]==[20000,100000,500000,1000000]
 assert not data['transitions'] and not (output/'matrix-5000000-samples.jsonl').exists()
 interrupted=r/'disk-space-interruption';interrupted.mkdir()
 for old in [r/'idle-repeat-exit.json',r/'idle-repeat.log',output/'matrix-5000000-load.jsonl']:
  if old.exists():shutil.move(str(old),str(interrupted/old.name))
 prior=json.dumps(data['cases'],sort_keys=True).encode()
 plan=dict(written_before_resumed_results=True,written_time_ns=time.time_ns(),reason='Disk filled while creating 5M fixtures, before any 5M timed sample. Four newly measured complete groups are retained unchanged; resume only the remaining size, then newly measure both memory passes.',completed_rows=[20000,100000,500000,1000000],completed_cases_sha256=hashlib.sha256(prior).hexdigest(),remaining_rows=[5000000],case_number=4,seconds_per_arm=5,free_bytes=shutil.disk_usage('/private/tmp').free,source_commit=json.loads((r/'build-manifest.json').read_text())['source_commit'])
 (r/'latest-resume-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
 shutil.copy2(__file__,r/'driver/resume-vm-clean-run.py')
 os.environ.update(json.loads((r/'calibration.json').read_text()));os.environ['PYTHONDONTWRITEBYTECODE']='1'
 args=type('Args',(),dict(fixtures=Path('/private/tmp/manticore-5045-review-20261113/sql'),output=output,duration=5))()
 binaries=dict(reference=Path('/private/tmp/manticore-5042-publish-review-20261113/candidate-searchd'),heap=Path('/private/tmp/manticore-adaptive-cache-review-20261113/searchd'),candidate=r/'searchd')
 assert {n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in binaries.items()}==data['binary_sha256']
 assert shutil.disk_usage('/private/tmp').free>1024**3
 data['cases'].append(vm_cache.matrix_case(5000000,4,binaries,args,mp.get_context('spawn')))
 assert hashlib.sha256(json.dumps(data['cases'][:4],sort_keys=True).encode()).hexdigest()==plan['completed_cases_sha256']
 data['completed']=True;data['resume_plan']='../latest-resume-plan.json';p.write_text(json.dumps(data,indent=2)+'\n')
 (r/'idle-repeat-exit.json').write_text(json.dumps(dict(exit_code=0,resumed=True,completed_time_ns=time.time_ns()))+'\n')
 subprocess.run([sys.executable,'/private/tmp/finish-vm-clean-run.py'],check=True)

if __name__=='__main__':main()
