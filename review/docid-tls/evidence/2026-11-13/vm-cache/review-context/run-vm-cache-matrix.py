from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
s=Path('/private/tmp/manticore-block-cache-evidence-20261113/review/docid-tls/repro/2026-11-13')
source=Path('/private/tmp/manticore-vm-cache-source-20261113')
base=Path('/private/tmp/manticore-5042-publish-review-20261113/candidate-searchd')
heap=Path('/private/tmp/manticore-adaptive-cache-review-20261113/searchd')
manifest=json.loads((r/'build-manifest.json').read_text())
assert hashlib.sha256((r/'searchd').read_bytes()).hexdigest()==manifest['binaries']['searchd']
assert hashlib.sha256(base.read_bytes()).hexdigest()=='b6658fc0f79f63eb12a1a55c807067b68ef629fedccede8329a769ae398cfb72'
assert hashlib.sha256(heap.read_bytes()).hexdigest()=='51c674f1ddbb1b676932bb9846708f55536063cd347deeadfa2605f38f3ce4a2'
assert json.loads((r/'full-tests.json').read_text())['tests']==537
assert json.loads((r/'full-tests.json').read_text())['failures']==0
for name in ['asan-ubsan','tsan']:assert (r/name/'tests.log').read_text().count('[  PASSED  ] 19 tests.')==20
changed=subprocess.check_output(['git','diff','--name-only','376fbf9988b2458ee196a5d92135c35a5121edc7','HEAD'],cwd=source,text=True).splitlines()
for name in changed:
 p=r/'candidate-source'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,p)
manifest.update(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),sources={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in changed},validation=dict(native_full_tests=537,focused_tests=19,native_repeats=20,asan_ubsan_repeats=20,tsan_repeats=20,leak_detection=False,api_smoke='passed'))
patch=subprocess.check_output(['git','diff','--binary','ad885be366eda4e897c828f05cb93ff04702d02c','HEAD'],cwd=source)
(r/'vm-cache.patch').write_bytes(patch);manifest['source_patch_sha256']=hashlib.sha256(patch).hexdigest()
(r/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
plan=dict(written_before_results=True,source_commit=manifest['source_commit'],source_patch_sha256=manifest['source_patch_sha256'],reader_tls=False,native_docid_budget=0,query_cache=0,matrix_rows=[20000,100000,500000,1000000,5000000],arms=['default16','heap_manual512','heap_adaptive512','vm_adaptive16','vm_adaptive512','cache_off'],rounds=6,seconds_per_arm=3,order='Six balanced Williams rounds; rotate server creation order by size.',longer_repeats=dict(rows=[20000,500000],rounds=6,seconds_per_arm=5,fresh_servers=True),memory_transitions=dict(passes=2,reverse_arm_order=True,arms=['heap_adaptive512','vm_adaptive512'],table_rows=5000000,phases=['5M ID range','20k hot prefix','5M ID range again'],seconds_per_stage=8,probe_interval_seconds=.2),load_control=dict(idle_gate_seconds=30,mean_idle_min=90,interval_idle_min=80,telemetry_seconds=1,retain_every_sample=True),interpretation='Equal-16 compares original default against proposed adaptive mode; equal-512 compares heap and VM adaptation. Default16 to adaptive512 includes a ceiling change. Small VM entry charges use 256-byte size classes; large mappings use page rounding. Unused space inside partially occupied 64 KiB regions and the bounded empty spare are additional. No reader TLS.')
(r/'measurement-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
driver=r/'driver';driver.mkdir(exist_ok=True)
for name in ['vm_cache.py','adaptive_cache.py','benchmark.py','block_cache_budgets.py','compare_blockcache.py','load_telemetry.py','scale_benchmark.py','support.py']:shutil.copy2(s/name,driver/name)
env=dict(os.environ);env.update(json.loads((r/'calibration.json').read_text()));env['PYTHONDONTWRITEBYTECODE']='1'
commands=[]
for name,options in [('matrix',[]),('repeat',['--rows','20000','500000','--duration','5','--matrix-only'])]:
 command=[sys.executable,str(driver/'vm_cache.py'),str(base),str(heap),str(r/'searchd'),'--fixtures','/private/tmp/manticore-5045-review-20261113/sql','--output',str(r/name),*options]
 commands.append(dict(phase=name,args=command));(r/'timing-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
 with (r/(name+'.log')).open('w') as log:
  proc=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  for line in proc.stdout:log.write(line);log.flush();print(name+': '+line,end='',flush=True)
  status=proc.wait()
 (r/(name+'-exit.json')).write_text(json.dumps(dict(exit_code=status,completed_time_ns=time.time_ns()))+'\n')
 assert status==0,(name,status)
