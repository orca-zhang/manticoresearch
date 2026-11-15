"""Create a new strict-idle experiment without altering saved runs or binaries."""
from pathlib import Path
import hashlib,json,shutil,subprocess
PARENT=Path('/work');ROOT=PARENT/'idle-20261114'
ROOT.mkdir(exist_ok=False);(ROOT/'logs').mkdir()
shutil.copytree(PARENT/'driver',ROOT/'driver',ignore=shutil.ignore_patterns('__pycache__'))
source=(PARENT/'driver/run_tls.py').read_text();current=source
replacements={
 'monitor.wait_idle(30, 60, 30, 600)':'monitor.wait_idle(30, 85, 70, 600)',
 "sample['external_cpu_mean_machine_percent'] > 45":"sample['external_cpu_mean_machine_percent'] > 15",
 "sample['external_cpu_peak_machine_percent'] > 70":"sample['external_cpu_peak_machine_percent'] > 30",
 'Existing host services retained; co-resident-service measurement':'Strict-idle retest requested after the user pauses background search tasks',
 '30 s mean idle >=60%, minimum >=30%; fixed before the first timed sample':'30 s mean idle >=85%, minimum >=70%; fixed before the first timed sample',
 'flag external mean CPU >45% machine or one-second peak >70%':'flag external mean CPU >15% machine or one-second peak >30%'
}
for old,new in replacements.items():
 assert current.count(old)==1,(old,current.count(old));current=current.replace(old,new)
for start,end in [('def pools_for(', '\ndef clone_data('),('def measure(', '\ndef cover_final(')]:
 assert source[source.index(start):source.index(end)]==current[current.index(start):current.index(end)]
(ROOT/'driver/run_tls.py').write_text(current)
(ROOT/'driver/run_tls_co_resident.py').write_text(source)
for label in ['baseline','tls']:(ROOT/('searchd-'+label)).symlink_to(PARENT/('searchd-'+label))
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol={'purpose':'Full independent reader-TLS retest after user pauses background search tasks',
 'upstream_base':'047d2f99522d78e0aa1de7e7dc945a9abe1b673a','tls_head':'019868e9f79d1bb2bd1f96dafb88ef20acd45418',
 'binary_sha256':{arm:digest(ROOT/('searchd-'+arm)) for arm in ['baseline','tls']},
 'fixed_before_timing':True,'rounds':6,'seconds_per_arm':5,'server_workers':8,
 'idle_gate':{'seconds':30,'mean_idle_at_least':85,'minimum_idle_at_least':70,'timeout_seconds':600},
 'flag_external_cpu':{'mean_machine_percent_above':15,'one_second_peak_machine_percent_above':30},
 'repeat_policy':'Repeat every telemetry-flagged complete primary comparison once in full; retain original and repeat, do not filter individual rounds',
 'primary_transport':'Original CPython HTTP at 1/8 clients; identical bytes in one write at 32 clients, matched within each comparison',
 'diagnostic_plan':'After primary comparisons, run original-transport 32-client point cases on/off, then upstream A/A32 point cases on/off. Retain errors without request retries; each diagnostic is a separate complete attempt.',
 'source_changes':replacements,
 'driver_sha256':{p.name:digest(p) for p in sorted((ROOT/'driver').glob('*.py'))},
 'fixture_source':'/work/fixtures','fixture_hashes_match_previous_run':None}
expected=json.loads((PARENT/'evidence/fixture-manifest.json').read_text())
actual={str(p.relative_to(PARENT/'fixtures')):digest(p) for p in sorted((PARENT/'fixtures').rglob('*')) if p.is_file()}
assert actual==expected
protocol['fixture_hashes_match_previous_run']=True
(ROOT/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
for script,args in [('run_tls.py',['--selfcheck']),('load_telemetry.py',[]),('coalesced_http.py',[]),('selfcheck_warmup.py',[])]:
 subprocess.run(['python3',str(ROOT/'driver'/script),*args],check=True)
print('Strict-idle workspace prepared; timing region/query pools and binary/fixture hashes unchanged',flush=True)
