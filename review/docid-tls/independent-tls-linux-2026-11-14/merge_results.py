"""Retain complete pairs across a diagnostic continuation, never individual rounds."""
from pathlib import Path
import hashlib,json,shutil,sys
sys.path.insert(0,"/work/driver")
from run_tls import cases
ROOT=Path('/work')
first=json.loads((ROOT/'measurement/results.json').read_text())
second=json.loads((ROOT/'coalesced32/results.json').read_text())
assert len(first['cases'])==19 and second['completed'] and len(second['cases'])==4
assert first['binary_sha256']==second['binary_sha256']
assert first['rounds']==second['rounds']==6 and first['seconds_per_arm']==second['seconds_per_arm']==5
original=(ROOT/'driver/run_tls_v1.py').read_text();current=(ROOT/'driver/run_tls.py').read_text()
for a,b in [('def pools_for(', '\ndef clone_data('), ('    before = resources(db.pid)', '\ndef cover_final(')]:
 assert original[original.index(a):original.index(b)]==current[current.index(a):current.index(b)]
selected={row['case']['name']:(row,phase) for phase,data in [('measurement',first),('coalesced32',second)] for row in data['cases']}
matrix=cases()
assert len(selected)==len(matrix)==23
out=ROOT/'merged';out.mkdir(exist_ok=False)
result=dict(first,cases=[],planned_cases=matrix,completed=True,transport_by_phase={'measurement':'Original CPython HTTP client','coalesced32':second['transport']},driver_revisions={phase:data['driver_sha256'] for phase,data in [('measurement',first),('coalesced32',second)]},
            continuation_note='Nineteen complete comparisons retained; all four 32-client cases use matched single-write HTTP framing in both arms. Engine binaries, query pools and server CPU timing region are unchanged. Every earlier completed/partial diagnostic is preserved separately.')
for case in matrix:
 name=case['name'];row,phase=selected[name];assert row['case']==case
 row=dict(row,driver_sha256=result['driver_revisions'][phase],source_phase=phase)
 result['cases'].append(row)
 for ending in ['-samples.jsonl','-load.jsonl']:
  shutil.copy2(ROOT/phase/(name+ending),out/(name+ending))
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
(out/'plan.json').write_text((ROOT/'measurement/plan.json').read_text())
diagnostics=[]
for phase,names in [('measurement',['churn-c32-20000-16m']),('continuation',None),('transport-aa32',None)]:
 folder=ROOT/phase
 if not folder.exists():continue
 for p in sorted(folder.glob('*-samples.jsonl')):
  name=p.name.removesuffix('-samples.jsonl')
  if names is not None and name not in names:continue
  rows=[json.loads(line) for line in p.read_text().splitlines()]
  diagnostics.append({'phase':phase,'case':name,'samples':rows,'validated_timed_queries':sum(x['sample']['completed'] for x in rows)})
aa_log=(ROOT/'logs/transport-aa32.log').read_text() if (ROOT/'logs/transport-aa32.log').exists() else ''
(ROOT/'diagnostics.json').write_text(json.dumps({'recorded_samples':sum(len(x['samples']) for x in diagnostics),'recorded_timed_queries':sum(x['validated_timed_queries'] for x in diagnostics),'upstream_aa32_connection_reset':'ConnectionResetError' in aa_log,'cases':diagnostics,'transport':second['transport']},indent=2)+'\n')
print('Merged all 23 complete paired cases; every earlier completed/partial attempt retained.')
