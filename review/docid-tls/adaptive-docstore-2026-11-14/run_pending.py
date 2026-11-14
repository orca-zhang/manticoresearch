#!/usr/bin/env python3
"""Run complete predeclared confirmations and controls, serially after the matrix."""
import json
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parent
deadline=time.monotonic()+1800
while True:
    data=json.loads((root/'measurement/results.json').read_text())
    if data.get('completed'):break
    assert time.monotonic()<deadline,'Primary matrix did not finish in 30 minutes'
    time.sleep(2)
for case in data['cases']:
    if any(s['quality_flag'] for a in case['arms'].values() for s in a['samples']):
        name=f"confirm-{case['rows']}"
        print('Complete confirmation:',case['name'],flush=True)
        with (root/(name+'.log')).open('w') as log:
            subprocess.run([sys.executable,str(root/'run_final.py'),'--rows',str(case['rows']),
                '--skip-memory','--output',str(root/name)],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
print('Run independent controls',flush=True)
with (root/'controls.log').open('w') as log:
    subprocess.run([sys.executable,str(root/'run_controls.py')],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
print('All scheduled measurement work completed',flush=True)
