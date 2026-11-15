from pathlib import Path
import json,time
root=Path('/work/idle-20261114')
status=json.loads((root/'status.json').read_text())
print('Status:',status['stage'],'phase:',status.get('phase','-'))
complete=[]
for phase in ['measurement','coalesced32']:
 p=root/phase/'results.json'
 if p.exists():complete.extend(json.loads(p.read_text())['cases'])
print('Primary complete:',len(complete),'/23')
for row in complete[-2:]:
 a,b=[row['arms'][k] for k in ['baseline','tls']]
 print(row['case']['name'],'QPS',round(a['qps_median'],1),'->',round(b['qps_median'],1),'change',round(row['qps_change_percent'],2),'CPU/query change',round(row['cpu_change_percent'],2),'flags',sum(s['quality_flag'] for arm in row['arms'].values() for s in arm['samples']),'gate mean/min',round(row['idle_gate']['idle_percent_mean'],1),round(row['idle_gate']['idle_percent_min'],1))
phase=status.get('phase','measurement')
p=root/'logs'/(phase+'.log')
if p.exists():print(p.read_text()[-700:])
telemetry=list((root/phase).glob('*-load.jsonl')) if (root/phase).exists() else []
if telemetry:
 p=max(telemetry,key=lambda x:x.stat().st_mtime)
 s=[json.loads(x) for x in p.read_text().splitlines()][-10:]
 print('Latest external CPU mean machine %:',round(sum(x['external_cpu_percent_machine'] for x in s)/len(s),1) if s else None)
if status['stage']=='failed':print(status.get('traceback',''))
p=root/'service-after-20261115.log'
if p.exists():print('Restoration:',p.read_text())
