from pathlib import Path
import hashlib,json,multiprocessing as mp,os,shutil,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
sys.path.insert(0,str(r/'driver'))
import vm_cache

def main():
 output=r/'idle-repeat';p=output/'matrix.json';data=json.loads(p.read_text())
 assert data['completed'] and len(data['cases'])==5 and not data['transitions']
 meta=json.loads((r/'build-manifest.json').read_text())
 assert data['binary_sha256']['candidate']==meta['binaries']['searchd']
 plan=dict(written_before_diagnostic_results=True,written_time_ns=time.time_ns(),reason='User requested all measurements anew, including both fresh-server broad/hot/broad memory passes.',source_commit=meta['source_commit'],passes=2,seconds_per_stage=8,arms=['heap_adaptive512','vm_adaptive512'],table_rows=5000000,unchanged_driver_sha256=data['scripts_sha256']['vm_cache.py'])
 (r/'latest-memory-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
 shutil.copy2(__file__,r/'driver/run-vm-clean-diagnostics.py')
 os.environ.update(json.loads((r/'calibration.json').read_text()))
 args=type('Args',(),dict(fixtures=Path('/private/tmp/manticore-5045-review-20261113/sql'),output=output))()
 binaries=dict(reference=Path('/private/tmp/manticore-5042-publish-review-20261113/candidate-searchd'),heap=Path('/private/tmp/manticore-adaptive-cache-review-20261113/searchd'),candidate=r/'searchd')
 assert {n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in binaries.items()}==data['binary_sha256']
 data['completed']=False;p.write_text(json.dumps(data,indent=2)+'\n')
 ctx=mp.get_context('spawn')
 for pass_number,labels in [(1,['heap_adaptive512','vm_adaptive512']),(2,['vm_adaptive512','heap_adaptive512'])]:
  for label in labels:
   data['transitions'].append(vm_cache.transition(pass_number,label,binaries,args,ctx))
   p.write_text(json.dumps(data,indent=2)+'\n')
 data['completed']=True;data['latest_memory_plan']='../latest-memory-plan.json';p.write_text(json.dumps(data,indent=2)+'\n')
 (r/'latest-memory-exit.json').write_text(json.dumps(dict(exit_code=0,completed_time_ns=time.time_ns()))+'\n')

if __name__=='__main__':main()
