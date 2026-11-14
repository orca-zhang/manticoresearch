"""Repeat the final two matched client variants in a fresh /work directory."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'driver'))
from run_tls import cases

low=[c['name'] for c in cases() if c['clients']!=32]
high=[c['name'] for c in cases() if c['clients']==32]
assert len(low)==19 and len(high)==4 and len(set(low+high))==23
if __name__=='__main__':
    if sys.argv[1:]==['--selfcheck']:
        print('Reproduction matrix selfcheck passed: 19 original-client + 4 single-write cases')
        sys.exit(0)
    assert len(sys.argv)==1
    base=['--fixtures',str(ROOT/'fixtures'),'--rounds','6','--duration','5']
    for script,output,matrix in [('run_tls.py','measurement',low),('run_coalesced32.py','coalesced32',high)]:
        subprocess.run([sys.executable,str(ROOT/'driver'/script),*base,'--output',str(ROOT/output),'--cases',*matrix],check=True)
    subprocess.run([sys.executable,str(ROOT/'merge_results.py')],check=True)
    data=json.loads((ROOT/'merged/results.json').read_text())
    flagged=[c['case']['name'] for c in data['cases'] if any(s['quality_flag'] for a in c['arms'].values() for s in a['samples'])]
    for suffix,script,names in [('low','run_tls.py',[n for n in flagged if n in low]),('high','run_coalesced32.py',[n for n in flagged if n in high])]:
        if names:
            subprocess.run([sys.executable,str(ROOT/'driver'/script),*base,'--output',str(ROOT/('repeat-'+suffix)),'--cases',*names],check=True)
