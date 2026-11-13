#!/usr/bin/env python3
"""Sample dedicated macOS daemons; profiling results are excluded from timed QPS."""
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import subprocess
import tempfile

from benchmark import ReaderServer, init_worker, worker
from scale_benchmark import fixed_queries
from support import clone_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ctx = mp.get_context("spawn")
    pools = fixed_queries(20000)
    manifest = {"profiling_only": True, "qps_values_discarded": True, "cases": []}
    for cache in (0, 128 * 1024**2):
        with tempfile.TemporaryDirectory(prefix="pr5045-profile-") as temp:
            folder = Path(temp)
            clone_data(args.fixture, folder)
            with ReaderServer(str(args.binary.resolve()), folder, cache).running() as db:
                go, ready = ctx.Event(), ctx.Queue()
                with ctx.Pool(8, initializer=init_worker, initargs=(go, ready)) as pool:
                    jobs = [pool.apply_async(worker, (db.port, queries, 8, False, None)) for queries in pools]
                    for _ in jobs:
                        ready.get(timeout=60)
                    command = ["/usr/bin/sample", str(db.pid), "5", "1", "-file",
                               str(args.output / f"cache-{cache}.txt")]
                    go.set()
                    sampled = subprocess.run(command, capture_output=True, text=True)
                    replies = [job.get(timeout=30) for job in jobs]
                    manifest["cases"].append({"block_cache_bytes": cache, "sample_command": command,
                                               "sample_exit": sampled.returncode,
                                               "sample_output": sampled.stdout + sampled.stderr,
                                               "checked_queries": sum(r["completed"] for r in replies)})
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print("profiled cache", cache, "sample exit", sampled.returncode, flush=True)


if __name__ == "__main__":
    main()
