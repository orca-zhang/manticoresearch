#!/usr/bin/env python3
"""After timing ends, rebuild/test the CMake-only follow-up and render evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parent
source=Path('/private/tmp/manticore-admission-source-20261114')
build=Path('/private/tmp/manticore-admission-review-20261114/build')
deadline=time.monotonic()+1800
while True:
    p=root/'controls/results.json'
    if p.exists() and json.loads(p.read_text()).get('completed'):break
    assert time.monotonic()<deadline,'Scheduled measurements did not finish'
    time.sleep(2)
env=os.environ.copy();env.update(json.loads((root/'calibration.json').read_text()))
env['GTEST_DICT']=str(source/'src/gtests')
commands=[('configure-publish.log',['cmake','-S',str(source),'-B',str(build)]),
          ('build-publish.log',['cmake','--build',str(build),'--target','searchd','gmanticoretest','-j','6']),
          ('native-publish.log',[str(build/'src/gtests/gmanticoretest')]),
          ('api-smoke-publish.log',['ctest','--test-dir',str(build),'-R','Perform API smoke test','--output-on-failure'])]
for name,cmd in commands:
    print(name,flush=True)
    with (root/name).open('w') as log:
        subprocess.run(cmd,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
with (root/'binary-publish-version.txt').open('w') as log:
    subprocess.run([str(build/'src/searchd'),'--version'],stdout=log,stderr=subprocess.STDOUT,check=True)
out=root/'report'
with (root/'summary-generation.log').open('w') as log:
    subprocess.run(['/private/tmp/manticore-tls-plot-20261114/bin/python',str(root/'summarize.py'),str(root),str(out)],stdout=log,stderr=subprocess.STDOUT,check=True)
subprocess.run([sys.executable,str(root/'write_docs.py'),str(root),str(out)],check=True)
print('Final local build/checks and English evidence complete',flush=True)
