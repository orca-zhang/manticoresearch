from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,shlex,shutil,subprocess,sys

r=Path('/private/tmp/manticore-adaptive-cache-review-20261113')
s=Path('/private/tmp/manticore-adaptive-cache-source-20261113')
b=Path('/private/tmp/manticore-5042-publish-build-20261113')
old='/private/tmp/manticore-5042-cache-publish-20261113'
objects=r/'objects';objects.mkdir(exist_ok=True)
database=json.loads((b/'compile_commands.json').read_text())
names=['docstore.cpp','skip_cache.cpp','sphinxutils.cpp','searchd.cpp','gtests_docstore_blockcache.cpp','gtests_searchd.cpp']
commands=[]
for name in names:
    e=next(e for e in database if Path(e['file']).name==name)
    args=[a.replace(old,str(s)).replace(str(s/'mcl'),old+'/mcl') for a in shlex.split(e['command'])]
    args[args.index('-o')+1]=str(objects/(name+'.o'))
    commands.append(dict(source=name,cwd=e['directory'],args=args))
(r/'build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
def compile_one(e):
    if '--only-tests' in sys.argv and not e['source'].startswith('gtests_'):
        return 0
    with (r/(e['source']+'-build.log')).open('w') as log:
        p=subprocess.run(e['args'],cwd=e['cwd'],stdout=log,stderr=subprocess.STDOUT)
    print(e['source'],'compile exit',p.returncode,flush=True)
    return p.returncode
with ThreadPoolExecutor(max_workers=3) as pool:
    statuses=list(pool.map(compile_one,commands))
assert statuses==[0]*len(names),statuses
archive=r/'liblmanticore.a'
base_library=b/'src/liblmanticore.a'
shutil.copy2(base_library,archive)
subprocess.run(['ar','r',str(archive),*[str(objects/(n+'.o')) for n in names[:3]]],check=True)
link_commands=[]
for target,folder in [('searchd','src'),('gmanticoretest','src/gtests')]:
    args=shlex.split((b/folder/f'CMakeFiles/{target}.dir/link.txt').read_text())
    args[args.index('-o')+1]=str(r/target)
    for i,a in enumerate(args):
        if a.endswith('liblmanticore.a'):args[i]=str(archive)
        elif Path(a).name in ('searchd.cpp.o','gtests_docstore_blockcache.cpp.o','gtests_searchd.cpp.o'):
            args[i]=str(objects/Path(a).name)
    link_commands.append(dict(target=target,cwd=str(b/folder),args=args))
    with (r/(target+'-link.log')).open('w') as log:
        subprocess.run(args,cwd=b/folder,stdout=log,stderr=subprocess.STDOUT,check=True)
    print('Linked',target,flush=True)
(r/'link-commands.json').write_text(json.dumps(link_commands,indent=2)+'\n')
changed=subprocess.check_output(['git','diff','--name-only'],cwd=s,text=True).splitlines()
manifest=dict(base_source_commit='376fbf9988b2458ee196a5d92135c35a5121edc7',reader_tls=False,
    scope='Recompile all six affected translation units using recorded Clang 21 -O2 commands; copy engine archive, replace changed objects, reuse unchanged engine/dependency objects. gtests_searchd.cpp includes searchd.cpp.',
    reused_base_archive_sha256=hashlib.sha256(base_library.read_bytes()).hexdigest(),
    sources={name:hashlib.sha256((s/name).read_bytes()).hexdigest() for name in changed},
    binaries={name:hashlib.sha256((r/name).read_bytes()).hexdigest() for name in ['searchd','gmanticoretest']})
(r/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Saved build/source/binary provenance.',flush=True)
