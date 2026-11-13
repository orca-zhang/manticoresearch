from pathlib import Path
import hashlib,json,shutil,subprocess,zipfile,re
src=Path('/private/tmp/manticore-adaptive-cache-review-20261113')
repo=Path('/private/tmp/manticore-block-cache-evidence-20261113')
root=repo/'review/docid-tls';dst=root/'evidence/2026-11-13/adaptive-cache'
s=Path('/private/tmp/manticore-adaptive-cache-source-20261113')
fm=src/'final-validation/manifest.json';m=json.loads(fm.read_text());m['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=s,text=True).strip();fm.write_text(json.dumps(m,indent=2)+'\n')
ctx=src/'final-validation/build-context';ctx.mkdir(exist_ok=True)
b=Path('/private/tmp/manticore-5042-publish-build-20261113')
for name in ['CMakeCache.txt','compile_commands.json','config/config.h']:
 p=ctx/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(b/name,p)
shutil.copy2(s/'src/taskmalloctrim.cpp',ctx/'taskmalloctrim.cpp')
(ctx/'compiler-version.txt').write_text(subprocess.check_output(['/usr/bin/c++','--version'],text=True))
shutil.copy2('/private/tmp/package-adaptive-evidence.py',src/'final-validation/package-adaptive-evidence.py')
shutil.copy2('/private/tmp/write-adaptive-report.py',src/'final-validation/write-adaptive-report.py')
analysis=src/'analysis-driver';analysis.mkdir(exist_ok=True)
for name in ['summarize_adaptive_cache.py','summarize_cache_budgets.py','plot_adaptive_cache.py']:
 shutil.copy2(root/'repro/2026-11-13'/name,analysis/name)
selected=[]
allowed_dirs={'sql','driver','analysis-driver','reference-source','candidate-source','final-validation','asan-ubsan','tsan','asan-ubsan-final','tsan-final','native-validated','asan-ubsan-validated','tsan-validated'}
allowed_suffix={'.json','.jsonl','.log','.csv','.patch','.cpp','.h','.md','.py','.txt','.rec'}
for path in sorted(src.rglob('*')):
 if not path.is_file():continue
 rel=path.relative_to(src)
 if len(rel.parts)>1 and rel.parts[0] not in allowed_dirs:continue
 if path.suffix not in allowed_suffix:continue
 assert not any(n in rel.parts for n in ['__pycache__','.git'])
 if path.suffix in {'.jsonl','.log','.json'}:
  content=path.read_text()
  # Check for common credential formats without printing matched values.
  assert not re.search(r'(?i)(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}|(?:--(?:api-)?token|--password)[= ]+\S+)',content),str(rel)
 target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);selected.append(rel)
# The successful smoke runner's output is compared to the source golden.
smoke=src/'smoke-build/api/libsphinxclient/smoke_ref.txt';gold=s/'api/libsphinxclient/smoke_ref.txt'
assert smoke.read_bytes()==gold.read_bytes()
(dst/'api-smoke-result.json').write_text(json.dumps(dict(result='passed',compared_output_sha256=hashlib.sha256(smoke.read_bytes()).hexdigest(),golden_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),cwd=str(smoke.parent),note='Successful output equals source golden; initial empty-fixture setup failure retained separately.'),indent=2)+'\n')
shutil.copy2(smoke,dst/'api-smoke-actual.txt')
manifest={str(f.relative_to(dst)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(dst.rglob('*')) if f.is_file() and f.name!='FILES_SHA256.json'}
(dst/'FILES_SHA256.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Copied evidence files:',len(manifest),'bytes:',sum(f.stat().st_size for f in dst.rglob('*') if f.is_file()))
# Package only the new experiment; the published budget snapshot is untouched.
files=[root/'ADAPTIVE_CACHE_2026-11-13.md',*dst.rglob('*'),*root.glob('figures/adaptive-cache-*')]
repro_names=['README.md','adaptive_cache.py','summarize_adaptive_cache.py','summarize_cache_budgets.py','plot_adaptive_cache.py','block_cache_budgets.py','load_telemetry.py','scale_benchmark.py','compare_blockcache.py','benchmark.py','support.py']
files += [root/'repro/2026-11-13'/n for n in repro_names]
files=sorted(set(f for f in files if f.is_file()))
zip_path=root/'attachments/adaptive-cache-evidence.zip'
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 hashes={}
 for f in files:
  name=str(f.relative_to(repo));content=f.read_bytes();z.writestr(name,content);hashes[name]=hashlib.sha256(content).hexdigest()
 z.writestr('FILES_SHA256.json',json.dumps(hashes,indent=2)+'\n')
 z.writestr('README.txt','Adaptive docstore cache experiment, 2026-11-13.\nStart with review/docid-tls/ADAPTIVE_CACHE_2026-11-13.md.\nThe archive contains this experiment, not every historical report linked by the guide.\nLegacy reports and artifacts remain available from the published repository.\nSource commit: ad885be366eda4e897c828f05cb93ff04702d02c.\nEntry reclamation is demonstrated; lower process RSS is not.\nBinaries, objects, archives, runtime data and allocator dumps are excluded.\n')
with zipfile.ZipFile(zip_path) as z:
 assert z.testzip() is None
 hashes=json.loads(z.read('FILES_SHA256.json'))
 for name,digest in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
print('Verified ZIP CRC and',len(hashes),'member SHA256s;',zip_path.stat().st_size,'bytes')
