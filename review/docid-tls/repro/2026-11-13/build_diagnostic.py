#!/usr/bin/env python3
"""Add counters to a separate diagnostic binary; never use it for timing."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("build", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
source, build, output = args.source.resolve(), args.build.resolve(), args.output.resolve()
output.mkdir(exist_ok=True)
text = (source / "src/docstore.cpp").read_text()
text = text.replace("#include <atomic>", """#include <atomic>
#include <cstdio>
struct ReaderDiagnostic_t
{
    std::atomic<uint64_t> lookups{0}, hits{0}, insertions{0}, deletions{0}, block_hits{0}, block_misses{0};
    ~ReaderDiagnostic_t()
    {
        printf("READER_DIAGNOSTIC %llu %llu %llu %llu %llu %llu\\n",
            (unsigned long long)lookups.load(), (unsigned long long)hits.load(),
            (unsigned long long)insertions.load(), (unsigned long long)deletions.load(),
            (unsigned long long)block_hits.load(), (unsigned long long)block_misses.load());
    }
};
static ReaderDiagnostic_t g_tReaderDiagnostic;
""")
old = "CSphReader * DocstoreReaders_c::GetReader ( int64_t iSessionId, int64_t iIndexId )\n{"
assert text.count(old) == 1
text = text.replace(old, old + "\n\tg_tReaderDiagnostic.lookups.fetch_add ( 1, std::memory_order_relaxed );")
assert text.count("\t\treturn tLast.m_pReader;") == 1
text = text.replace("\t\treturn tLast.m_pReader;", "\t{\n\tg_tReaderDiagnostic.hits.fetch_add ( 1, std::memory_order_relaxed );\n\t\treturn tLast.m_pReader;\n\t}")
text = text.replace("\tm_iTotalReaderSize += iBufferSize;", "\tg_tReaderDiagnostic.insertions.fetch_add ( 1, std::memory_order_relaxed );\n\tm_iTotalReaderSize += iBufferSize;")
text = text.replace("\tm_iTotalReaderSize -= pReader->GetBufferSize();", "\tg_tReaderDiagnostic.deletions.fetch_add ( 1, std::memory_order_relaxed );\n\tm_iTotalReaderSize -= pReader->GetBufferSize();")
old = "\tbool bFromCache = pBlockCache && pBlockCache->Find ( { m_iIndexId, tBlock.m_tOffset }, tBlockData );"
assert text.count(old) == 1
text = text.replace(old, old + "\n\t(bFromCache ? g_tReaderDiagnostic.block_hits : g_tReaderDiagnostic.block_misses).fetch_add ( 1, std::memory_order_relaxed );")
cpp, obj = output / "docstore.cpp", output / "docstore.o"
cpp.write_text(text)
commands = json.loads((build / "compile_commands.json").read_text())
command = shlex.split(next(c["command"] for c in commands if c["file"] == str(source / "src/docstore.cpp")))
command[command.index("-o") + 1] = str(obj)
command[command.index("-c") + 1] = str(cpp)
subprocess.run(command, cwd=build / "src", check=True)
link = shlex.split((build / "src/CMakeFiles/searchd.dir/link.txt").read_text())
link.insert(link.index("-o"), str(obj))
link[link.index("-o") + 1] = str(output / "searchd")
subprocess.run(link, cwd=build / "src", check=True)
(output / "manifest.json").write_text(json.dumps({
    "commands": [command, link], "diagnostic_only": True,
    "source_sha256": hashlib.sha256(cpp.read_bytes()).hexdigest(),
    "binary_sha256": hashlib.sha256((output / "searchd").read_bytes()).hexdigest()
}, indent=2) + "\n")
