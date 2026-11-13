from pathlib import Path
import json,subprocess,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
sys.path.insert(0,str(r/'driver'))
from load_telemetry import LoadMonitor
print('Waiting for user-managed competing jobs to finish; no benchmark servers active.',flush=True)
with LoadMonitor(r/'idle-wait-preflight-load.jsonl') as monitor:
 gate=monitor.wait_idle(seconds=30,mean_idle=90,min_idle=80,timeout=3600)
(r/'idle-wait-preflight-result.json').write_text(json.dumps(dict(passed=True,gate=gate,completed_time_ns=time.time_ns()),indent=2)+'\n')
print('Preflight idle gate passed; launching fresh-server full rerun.',flush=True)
subprocess.run([sys.executable,'/private/tmp/run-vm-quiet-repeat.py'],check=True)
