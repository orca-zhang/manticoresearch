from pathlib import Path
import os,subprocess,sys,time
r=Path('/private/tmp/manticore-vm-cache-review-20261113')
print('Waiting for the fresh five-size matrix before new memory diagnostics.',flush=True)
while not (r/'idle-repeat-exit.json').exists():time.sleep(2)
import json
assert json.loads((r/'idle-repeat-exit.json').read_text())['exit_code']==0
env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
with (r/'latest-memory.log').open('w') as log:
 p=subprocess.Popen([sys.executable,'/private/tmp/run-vm-clean-diagnostics.py'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 for line in p.stdout:log.write(line);log.flush();print(line,end='',flush=True)
 status=p.wait()
assert status==0,status
