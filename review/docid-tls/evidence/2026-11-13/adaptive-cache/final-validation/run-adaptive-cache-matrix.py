from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time

r=Path('/private/tmp/manticore-adaptive-cache-review-20261113')
s=Path('/private/tmp/manticore-block-cache-evidence-20261113/review/docid-tls/repro/2026-11-13')
m=json.loads((r/'build-manifest.json').read_text())
assert hashlib.sha256((r/'searchd').read_bytes()).hexdigest()==m['binaries']['searchd']
baseline=Path('/private/tmp/manticore-5042-publish-review-20261113/candidate-searchd')
assert hashlib.sha256(baseline.read_bytes()).hexdigest()=='b6658fc0f79f63eb12a1a55c807067b68ef629fedccede8329a769ae398cfb72'
snapshot=r/'driver';snapshot.mkdir(exist_ok=True)
for name in ['adaptive_cache.py','benchmark.py','block_cache_budgets.py','compare_blockcache.py','load_telemetry.py','scale_benchmark.py','support.py']:
    shutil.copy2(s/name,snapshot/name)
command=[sys.executable,str(s/'adaptive_cache.py'),str(baseline),str(r/'searchd'),
         '--fixtures','/private/tmp/manticore-5045-review-20261113/sql','--output',str(r/'sql')]
(r/'matrix-command.json').write_text(json.dumps(command,indent=2)+'\n')
env=dict(os.environ);env.update(json.loads((r/'calibration.json').read_text()));env['PYTHONDONTWRITEBYTECODE']='1'
with (r/'matrix.log').open('w') as log:
    process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in process.stdout:
        log.write(line);log.flush();print(line,end='',flush=True)
    status=process.wait()
(r/'matrix-exit.json').write_text(json.dumps(dict(exit_code=status,completed_time_ns=time.time_ns()))+'\n')
sys.exit(status)
