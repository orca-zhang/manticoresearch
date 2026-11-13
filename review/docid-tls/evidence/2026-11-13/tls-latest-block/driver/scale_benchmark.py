#!/usr/bin/env python3
"""Vary dataset size and block-cache budget while keeping the query generator fixed."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import statistics
import tempfile
import urllib.parse

import benchmark
from benchmark import ReaderServer, make_fixture, run_case, value
from support import clone_data


SIZES = (20000, 100000, 500000, 1000000, 5000000)


def fixed_queries(docs, count=False):
    # Match the original upstream-only driver's seed, templates and projections.
    rng = random.Random(257 + 256)
    result = []
    for _ in range(8):
        queries = []
        for _ in range(20):
            ids = sorted(rng.sample(range(1, docs + 1), 256))
            clause = ",".join(map(str, ids))
            sql = (f"SELECT count(*) AS n FROM docs WHERE id IN ({clause})" if count else
                   f"SELECT id,body FROM docs WHERE id IN ({clause}) ORDER BY id ASC LIMIT 256")
            expected = [{"n": 256}] if count else [{"id": i, "body": value(i)} for i in ids]
            queries.append((urllib.parse.urlencode({"query": sql}).encode(), expected))
        result.append(queries)
    return result


def fixture_info(folder, docs):
    files = list((folder / "data").rglob("*.spds"))
    return {"docs": docs, "logical_stored_text_bytes": docs * 128,
            "disk_chunks": len(files), "spds_bytes": sum(p.stat().st_size for p in files),
            "disk_bytes": sum(p.stat().st_size for p in (folder / "data").rglob("*") if p.is_file())}


def budgets(index, docs):
    sizes = [0, 16 * 1024**2, 128 * 1024**2]
    sizes = sizes[index % 3:] + sizes[:index % 3]
    if docs == 5000000:
        sizes.append(512 * 1024**2)
    return sizes


def case_for(docs, cache, *, count=False, aa=False):
    return {"name": f"scale-{docs}-cache{cache}-{'count' if count else 'aa' if aa else 'text'}",
            "docs": docs, "cache": cache, "clients": 8, "batch": 256,
            "count": count, "aa": aa}


def add_memory(entry):
    for arm in entry["arms"].values():
        arm["rss_bytes_median"] = statistics.median(s["rss_bytes"] for s in arm["samples"])


def cache_effects(output):
    references = {c["case"]["docs"]: c for c in output["cases"]
                  if c["case"]["cache"] == 0 and not c["case"]["count"] and not c["case"]["aa"]}
    for entry in output["cases"]:
        case = entry["case"]
        if case["count"] or case["aa"] or case["docs"] not in references:
            continue
        base = references[case["docs"]]
        for label, arm in entry["arms"].items():
            arm["qps_change_vs_cache0_percent"] = (arm["qps_median"] / base["arms"][label]["qps_median"] - 1) * 100
            arm["rss_change_vs_cache0_bytes"] = arm["rss_bytes_median"] - base["arms"][label]["rss_bytes_median"]


def selfcheck():
    assert sum(len(budgets(i, n)) for i, n in enumerate(SIZES)) == 16
    queries = fixed_queries(20000)
    assert len(queries) == 8 and all(len(q) == 20 for q in queries)
    assert queries == fixed_queries(20000)
    assert all(len(expected) == 256 for q in queries for _, expected in q)
    assert all(expected == [{"n": 256}] for q in fixed_queries(20000, True) for _, expected in q)
    fake = {"cases": []}
    for cache, qps, rss in [(0, 100, 10), (16, 120, 15)]:
        fake["cases"].append({"case": case_for(20000, cache), "arms": {
            label: {"qps_median": qps, "rss_bytes_median": rss} for label in ("reference", "tls")}})
    cache_effects(fake)
    assert abs(fake["cases"][1]["arms"]["tls"]["qps_change_vs_cache0_percent"] - 20) < 1e-9
    assert fake["cases"][1]["arms"]["tls"]["rss_change_vs_cache0_bytes"] == 5
    print("scale harness selfcheck passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="?", type=Path)
    parser.add_argument("tls", nargs="?", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.reference and args.tls and args.work and args.output
    assert args.rounds >= 2 and args.duration > 0
    binaries = {"reference": str(args.reference.resolve()), "tls": str(args.tls.resolve())}
    output = {"platform": platform.platform(), "matrix": "dataset size x block-cache budget",
              "rounds": args.rounds, "seconds_per_arm": args.duration,
              "server_threads": 8, "clients": 8, "batch": 256, "payload_bytes": 128,
              "block_bytes": 16384, "compression": "lz4", "queries_per_client": 20,
              "generation_policy": "Original PR #5045, one global generation; no DocID native cache",
              "reader_buffer_budget_bytes": 8388608,
              "scripts_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [Path(__file__), Path(benchmark.__file__)]},
              "calibration": {k: v for k, v in os.environ.items() if k.startswith("MANTICORE_")},
              "binaries": {label: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                           for label, path in binaries.items()}, "fixtures": {}, "cases": []}
    args.work.mkdir(parents=True, exist_ok=True)
    ctx = mp.get_context("spawn")
    for index, docs in enumerate(SIZES):
        fixture = args.work / f"fixture-{docs}"
        if not fixture.exists():
            print(f"building fixture {docs}", flush=True)
            make_fixture(binaries["reference"], fixture, docs)
        output["fixtures"][str(docs)] = fixture_info(fixture, docs)
        queries = fixed_queries(docs)
        print("fixture", output["fixtures"][str(docs)], flush=True)
        for cache in budgets(index, docs):
            with tempfile.TemporaryDirectory(prefix="scale-arms-", dir=args.work) as temp, ExitStack() as stack:
                servers = {}
                for label, binary in binaries.items():
                    folder = Path(temp) / label
                    folder.mkdir()
                    clone_data(fixture, folder)
                    servers[label] = stack.enter_context(ReaderServer(binary, folder, cache).running())
                selected = [(case_for(docs, cache), servers, queries)]
                if cache == 0:
                    selected.append((case_for(docs, cache, count=True), servers, fixed_queries(docs, True)))
                if docs in (1000000, 5000000) and cache == 16777216:
                    folder = Path(temp) / "aa"
                    folder.mkdir()
                    clone_data(fixture, folder)
                    aa = stack.enter_context(ReaderServer(binaries["reference"], folder, cache).running())
                    selected.append((case_for(docs, cache, aa=True), {"reference": servers["reference"], "tls": aa}, queries))
                for case, used_servers, pools in selected:
                    args.order_offset = len(output["cases"]) % 2
                    print("starting", case["name"], flush=True)
                    entry = run_case(case, used_servers, ctx, args, query_sets=pools)
                    add_memory(entry)
                    output["cases"].append(entry)
                    cache_effects(output)
                    args.output.write_text(json.dumps(output, indent=2) + "\n")
                    print(f"{case['name']}: QPS {entry['qps_change_percent']:+.2f}% "
                          f"CPU/query {entry['server_cpu_change_percent']:+.2f}%", flush=True)
    output["completed"] = True
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
