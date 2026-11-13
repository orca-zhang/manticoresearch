from pathlib import Path
import hashlib,json,re,shutil,subprocess,zipfile
repo=Path('/private/tmp/manticore-block-cache-evidence-20261113');root=repo/'review/docid-tls'
src=Path('/private/tmp/manticore-vm-cache-review-20261113');source=Path('/private/tmp/manticore-vm-cache-source-20261113');dst=root/'evidence/2026-11-13/vm-cache'
allowed={'.json','.jsonl','.log','.csv','.patch','.cpp','.h','.md','.py','.txt','.rec'}
dirs={'matrix','repeat','idle-repeat','idle-wait-attempt-1','disk-space-interruption','driver','candidate-source','asan-ubsan','tsan','review-context','analysis-driver'}
ctx=src/'review-context';ctx.mkdir(exist_ok=True)
for name in ['build-vm-cache.py','sanitize-vm-cache.py','run-vm-cache-matrix.py','run-vm-quiet-repeat.py','resume-vm-clean-run.py','run-vm-clean-diagnostics.py','finish-vm-clean-run.py','wait-vm-idle.py','write-vm-report.py','write-vm-index.py','package-vm-evidence.py']:shutil.copy2(Path('/private/tmp')/name,ctx/name)
b=Path('/private/tmp/manticore-5042-publish-build-20261113')
for name in ['CMakeCache.txt','compile_commands.json','config/config.h']:
 target=ctx/'build-context'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(b/name,target)
(ctx/'build-context/compiler-version.txt').write_text(subprocess.check_output(['/usr/bin/c++','--version'],text=True))
analysis=src/'analysis-driver';analysis.mkdir(exist_ok=True)
for name in ['summarize_vm_cache.py','summarize_cache_budgets.py','plot_vm_cache.py']:shutil.copy2(root/'repro/2026-11-13'/name,analysis/name)
def copy_evidence(base,target,include_dirs=None):
 count=0
 for p in sorted(base.rglob('*')):
  if not p.is_file() or p.suffix not in allowed:continue
  rel=p.relative_to(base)
  if '__pycache__' in rel.parts:continue
  if include_dirs is not None and len(rel.parts)>1 and rel.parts[0] not in include_dirs:continue
  if p.suffix in {'.json','.jsonl','.log'}:
   assert not re.search(r'(?i)(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}|(?:--(?:api-)?token|--password)[= ]+\S+)',p.read_text()),str(rel)
  q=target/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q);count+=1
 return count
print('Final files copied',copy_evidence(src,dst,dirs))
diag=Path('/private/tmp/manticore-vm-cache-page-diagnostic-20261113')
print('Diagnostic files copied',copy_evidence(diag,dst/'pre-packing-diagnostic',{'matrix','driver','candidate-source','asan-ubsan','tsan'}))
for folder in [dst,dst/'pre-packing-diagnostic']:
 m=json.loads((folder/'build-manifest.json').read_text())
 for name,digest in m['sources'].items():assert hashlib.sha256((folder/'candidate-source'/name).read_bytes()).hexdigest()==digest,name
 assert hashlib.sha256((folder/'vm-cache.patch').read_bytes()).hexdigest()==m['source_patch_sha256']
actual=src/'smoke-build/api/libsphinxclient/smoke_ref.txt';gold=source/'api/libsphinxclient/smoke_ref.txt'
assert actual.read_bytes()==gold.read_bytes();shutil.copy2(actual,dst/'api-smoke-actual.txt')
(dst/'api-smoke-result.json').write_text(json.dumps(dict(passed=True,actual_sha256=hashlib.sha256(actual.read_bytes()).hexdigest(),golden_sha256=hashlib.sha256(gold.read_bytes()).hexdigest()),indent=2)+'\n')
files={str(f.relative_to(dst)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(dst.rglob('*')) if f.is_file() and f.name!='FILES_SHA256.json'}
(dst/'FILES_SHA256.json').write_text(json.dumps(files,indent=2)+'\n')
paths=[root/'ADAPTIVE_CACHE_2026-11-13.md',*dst.rglob('*'),*root.glob('figures/adaptive-cache-*')]
for n in ['README.md','vm_cache.py','summarize_vm_cache.py','summarize_cache_budgets.py','plot_vm_cache.py','adaptive_cache.py','block_cache_budgets.py','benchmark.py','compare_blockcache.py','load_telemetry.py','scale_benchmark.py','support.py']:paths.append(root/'repro/2026-11-13'/n)
paths=sorted(set(p for p in paths if p.is_file()))
archive=root/'attachments/adaptive-cache-evidence.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 hashes={}
 for p in paths:
  name=str(p.relative_to(repo));data=p.read_bytes();z.writestr(name,data);hashes[name]=hashlib.sha256(data).hexdigest()
 z.writestr('FILES_SHA256.json',json.dumps(hashes,indent=2)+'\n')
 z.writestr('README.txt','Current adaptive docstore cache evidence. Start with review/docid-tls/ADAPTIVE_CACHE_2026-11-13.md.\nContains final default/adaptive measurements and a separate stopped pre-packing diagnostic.\nBinaries, objects, archives and runtime data are excluded.\nHistorical reports/artifacts linked by the guide remain in the published repository.\n')
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for name,digest in json.loads(z.read('FILES_SHA256.json')).items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
print('Verified',len(hashes),'ZIP member SHA256s and CRC;',archive.stat().st_size,'bytes.')
