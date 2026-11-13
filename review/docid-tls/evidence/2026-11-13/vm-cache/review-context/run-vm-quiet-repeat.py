from pathlib import Path
import hashlib,json,os,subprocess,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
manifest=json.loads((r/'build-manifest.json').read_text())
base=Path('/private/tmp/manticore-5042-publish-review-20261113/candidate-searchd');heap=Path('/private/tmp/manticore-adaptive-cache-review-20261113/searchd');candidate=r/'searchd'
assert hashlib.sha256(candidate.read_bytes()).hexdigest()==manifest['binaries']['searchd']
args=[sys.executable,str(r/'driver/vm_cache.py'),str(base),str(heap),str(candidate),'--fixtures','/private/tmp/manticore-5045-review-20261113/sql','--output',str(r/'idle-repeat'),'--duration','5','--matrix-only']
assert not (r/'idle-repeat').exists()
plan=dict(written_before_results=True,written_time_ns=time.time_ns(),reason='User agreed to pause competing OCR/FFmpeg tasks after earlier measurements had external-load flags. Repeat all five sizes with unchanged binaries/driver, fresh servers and six balanced 5-second rounds.',source_commit=manifest['source_commit'],rows=[20000,100000,500000,1000000,5000000],rounds=6,seconds_per_arm=5,arms=['default16','heap_manual512','heap_adaptive512','vm_adaptive16','vm_adaptive512','cache_off'],reader_tls=False,memory_diagnostics_repeated=False,retain_every_sample=True,args=args,binary_sha256={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in [('reference',base),('heap',heap),('candidate',candidate)]})
(r/'idle-repeat-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
env=dict(os.environ);env.update(json.loads((r/'calibration.json').read_text()));env['PYTHONDONTWRITEBYTECODE']='1'
with (r/'idle-repeat.log').open('w') as log:
 proc=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 for line in proc.stdout:log.write(line);log.flush();print(line,end='',flush=True)
 status=proc.wait()
(r/'idle-repeat-exit.json').write_text(json.dumps(dict(exit_code=status,completed_time_ns=time.time_ns()))+'\n')
assert status==0,status
