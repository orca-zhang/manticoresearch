"""Attribute a failed diagnostic to its next planned interval, preserving inference."""
from pathlib import Path
import json,sys
root=Path(sys.argv[1]);reference=json.loads((root/'reference-results.json').read_text());protocol=json.loads((root/'protocol.json').read_text());statuses=json.loads((root/'diagnostic-status.json').read_text());audit=[]
for status in statuses:
 phase=status['phase'];folder=root/phase;plan=json.loads((folder/'plan.json').read_text());assert len(plan['planned_cases'])==1
 assert plan['driver_sha256']==protocol['driver_sha256']['run_tls.py']
 assert plan['binary_sha256']==({'baseline':reference['binary_sha256']['baseline'],'tls':reference['binary_sha256']['baseline']} if status['same_upstream_binary_both_arms'] else reference['binary_sha256'])
 name=plan['planned_cases'][0]['name'];journal=folder/(name+'-samples.jsonl')
 samples=[json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
 expected=[(round_id,arm) for round_id in range(plan['rounds']) for arm in (['baseline','tls'] if round_id%2==0 else ['tls','baseline'])]
 assert [(x['sample']['round'],x['arm']) for x in samples]==expected[:len(samples)]
 item={'phase':phase,'returncode':status['returncode'],'recorded_samples':len(samples),'binary_sha256':plan['binary_sha256'],'same_upstream_binary_both_arms':status['same_upstream_binary_both_arms']}
 if status['returncode']:
  log=(root/'logs'/(phase+'.log')).read_text()
  item['connection_reset']='ConnectionResetError' in log
  if item['connection_reset'] and len(samples)<len(expected) and 'sample = measure(' in log:
   r,arm=expected[len(samples)]
   item.update(next_planned_round_zero_based=r,next_planned_arm=arm,active_binary_sha256=plan['binary_sha256'][arm],active_binary_is_unmodified_upstream=plan['binary_sha256'][arm]==plan['binary_sha256']['baseline'],attribution_method='Inferred from the next planned interval after the validated journal prefix; traceback fails inside measure before journal append. Every diagnostic selects one case, numbered zero, so AB/BA ordering is fixed.')
 audit.append(item)
(root/'diagnostic-failure-provenance.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
