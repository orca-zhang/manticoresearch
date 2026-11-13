#!/usr/bin/env python3
"""Focused cache sanitizers using unchanged dependencies from a native build."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("build", type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--sanitizer", required=True, choices=["address,undefined", "thread"])
parser.add_argument("--repeat", type=int, default=20)
args = parser.parse_args()
source, build, output = args.source.resolve(), args.build.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
commands = json.loads((build / "compile_commands.json").read_text())
files = ["src/docstore.cpp", "src/fileio.cpp", "src/docidlookupcache.cpp", "src/docidlookup.cpp",
         "src/gtests/gtests_docidcache.cpp", "src/gtests/gtests_docidlookup.cpp",
         "src/gtests/gtests_docstore_blockcache.cpp"]
flags = ["-fsanitize=" + args.sanitizer, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-O1"]
objects, executed = [], []
for name in files:
    entry = next(c for c in commands if c["file"] == str(source / name))
    command = shlex.split(entry["command"])
    obj = str(output / (Path(name).stem + ".o"))
    command[command.index("-o") + 1] = obj
    command += flags
    executed.append(command)
    print("compile", name, flush=True)
    subprocess.run(command, cwd=entry["directory"], check=True)
    objects.append(obj)
link = shlex.split((build / "src/gtests/CMakeFiles/gmanticoretest.dir/link.txt").read_text())
index = link.index("-o")
replaced = tuple(Path(f).name + ".o" for f in files if "/gtests/" in f)
link = [x for x in link[:index] if not x.endswith(replaced)] + objects + link[index:]
link[link.index("-o") + 1] = str(output / "cache-tests")
link += flags
executed.append(link)
subprocess.run(link, cwd=build / "src/gtests", check=True)
test = [str(output / "cache-tests"),
        "--gtest_filter=NativeDocidCache.*:UuidDocidLookupTest.*:DocstoreBlockCacheTest.*",
        "--gtest_repeat=" + str(args.repeat)]
executed.append(test)
(output / "commands.json").write_text(json.dumps(executed, indent=2) + "\n")
subprocess.run(test, cwd=output, check=True)
