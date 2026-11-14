"""Standard-library support for independent upstream SQL benchmarks."""
import contextlib
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RUsageV2(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            "user", "system", "idle_wakeups", "interrupt_wakeups", "pageins",
            "wired", "resident", "footprint", "start", "exit", "child_user",
            "child_system", "child_idle", "child_interrupt", "child_pageins",
            "child_elapsed", "read_bytes", "written_bytes",
        )
    ]


TIMEBASE = None
if sys.platform == "darwin":
    LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    LIBPROC.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    LIBPROC.proc_pid_rusage.restype = ctypes.c_int
    class Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
    TIMEBASE = Timebase()
    assert ctypes.CDLL(None).mach_timebase_info(ctypes.byref(TIMEBASE)) == 0


def resources(pid):
    if sys.platform == "darwin":
        usage = RUsageV2()
        if LIBPROC.proc_pid_rusage(pid, 2, ctypes.byref(usage)):
            raise OSError(ctypes.get_errno(), "proc_pid_rusage")
        ticks = usage.user + usage.system
        return {"cpu_ticks": ticks, "cpu_ns": ticks * TIMEBASE.numer // TIMEBASE.denom,
                "rss_bytes": usage.resident,
                "footprint_bytes": usage.footprint}
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"cpu_ns": (int(fields[11]) + int(fields[12])) * 1_000_000_000 // os.sysconf("SC_CLK_TCK"),
            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")}



class Server:
    def __init__(self, binary, root, threads=None):
        self.binary, self.root = binary, root
        self.port = free_port()
        (root / "data").mkdir(exist_ok=True)
        self.config = root / "manticore.conf"
        threads_config = f"threads = {threads}\n" if threads is not None else ""
        self.config.write_text(
            "searchd {\n"
            f"listen = 127.0.0.1:{self.port}:http\n"
            f"data_dir = {root / 'data'}\n"
            f"log = {root / 'searchd.log'}\n"
            f"pid_file = {root / 'searchd.pid'}\n"
            "buddy_path =\n"
            f"{threads_config}"
            "}\n"
        )

    def sql(self, query):
        return self.sql_all(query)[0]

    def sql_all(self, query):
        body = urllib.parse.urlencode({"query": query}).encode()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/sql?mode=raw", body, timeout=30
            ) as response:
                results = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{query[:150]}: {error.read().decode()}") from error
        for result in results:
            if result.get("error"):
                raise RuntimeError(f"{query[:150]}: {result['error']}")
        return results

    @contextlib.contextmanager
    def running(self):
        with (self.root / "console.log").open("a") as output:
            proc = subprocess.Popen(
                [self.binary, "--config", str(self.config), "--nodetach"],
                stdout=output, stderr=subprocess.STDOUT,
            )
            self.pid = proc.pid
            try:
                deadline = time.monotonic() + 30
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f"searchd exited with status {proc.returncode}:\n" + (self.root / "console.log").read_text())
                    try:
                        self.sql("SHOW STATUS")
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(0.05)
                yield self
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                if proc.returncode:
                    raise RuntimeError(f"searchd exited with status {proc.returncode}:\n" + (self.root / "console.log").read_text())



def clone_data(source, target):
    shutil.copytree(source / "data", target / "data")
    # The registry contains absolute table paths. Only rewrite those copied
    # JSON files; the original fixture and binary table files stay untouched.
    for path in (target / "data").rglob("*.json"):
        text = path.read_text()
        path.write_text(text.replace(str(source / "data"), str(target / "data")))
