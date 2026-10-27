import argparse,pathlib,re,shlex,subprocess
parser=argparse.ArgumentParser(description="Focused reader sanitizer run using a Unix Makefiles engine build; unchanged dependencies are reused.")
parser.add_argument('repository',type=pathlib.Path)
parser.add_argument('build',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
parser.add_argument('--sanitizer',choices=['address,undefined','thread'],required=True)
parser.add_argument('--repeat',type=int,default=20)
args=parser.parse_args()
repo=args.repository.resolve()
build=args.build.resolve()
out=args.output.resolve()
out.mkdir(parents=True,exist_ok=True)
mode=args.sanitizer
flags=['-fsanitize='+mode,'-fno-omit-frame-pointer','-O1']
objects=[]
for source,target in [('src/docstore.cpp','src/CMakeFiles/lmanticore.dir'),('src/fileio.cpp','src/CMakeFiles/lmanticore.dir'),('src/gtests/gtests_docstore_readers.cpp','src/gtests/CMakeFiles/gmanticoretest.dir')]:
    content=(build/target/'flags.make').read_text()
    options=[]
    for name in ['CXX_DEFINES','CXX_INCLUDES','CXX_FLAGS']:
        options += shlex.split(re.search('^'+name+' = (.*)$',content,re.M)[1])
    obj=out/(pathlib.Path(source).stem+'-'+mode.replace(',','-')+'.o')
    cmd=['/usr/bin/c++']+options+flags+['-c',str(repo/source),'-o',str(obj)]
    print(shlex.join(cmd),flush=True)
    subprocess.run(cmd,check=True)
    objects.append(str(obj))
link=shlex.split((build/'src/gtests/CMakeFiles/gmanticoretest.dir/link.txt').read_text())
start=link.index('-o')
# Run just the public docstore tests, reusing unchanged engine dependencies.
link=[x for x in link[:start] if not x.endswith('gtests_docstore_readers.cpp.o')] + objects + link[start:]
link[link.index('-o')+1]=str(out/('readers-'+mode.replace(',','-')))
subprocess.run(link+flags,cwd=build/'src/gtests',check=True)
subprocess.run([str(out/('readers-'+mode.replace(',','-'))),'--gtest_filter=DocstoreReadersTest.*',f'--gtest_repeat={args.repeat}'],cwd=out,check=True)
