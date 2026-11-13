#!/usr/bin/env python3
"""Compare cache off/on in the same binary, including very small datasets."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import statistics
import tempfile

from benchmark import ReaderServer, make_fixture, queries_for, run_case
from compare_blockcache import lifecycle, pools_for
from scale_benchmark import fixture_info
from support import clone_data


def cases():
    result = [dict(name=f"rows{docs}-c8-b64", docs=docs, clients=8, batch=64)
              for docs in (256, 1024, 4096, 20000)]
    result += [dict(name=f"rows{docs}-c8-point", docs=docs, clients=8, batch=1)
               for docs in (16, 256, 20000)]
    result += [dict(name=f"rows20000-c{clients}-b256", docs=20000, clients=clients, batch=256)
               for clients in (1, 8)]
    result.append(dict(name="rows256-c1-b64", docs=256, clients=1, batch=64))
    return result


def selfcheck():
    matrix = cases()
    assert len(matrix) == len({c["name"] for c in matrix}) == 10
    for case in matrix:
        pools = pools_for(case)
        assert len(pools) == case["clients"]
        assert all(len(expected) == case["batch"] for pool in pools for _, expected in pool)
        if case["batch"] != 256:
            assert pools == [queries_for(case["docs"], case["batch"], i)
                             for i in range(case["clients"])]
    print("cache toggle selfcheck passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", nargs="?", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--docid-cache", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--order-offset", type=int, default=0)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.binary and args.fixtures and args.output
    assert args.rounds >= 2 and args.duration > 0
    binary = str(args.binary.resolve())
    selected = [c for c in cases() if not args.cases or c["name"] in args.cases]
    assert selected and (not args.cases or len(selected) == len(args.cases))
    output = {"comparison": "Same PR #5042 binary WITHOUT reader TLS; cache disabled vs default 16 MiB",
              "arm_labels": {"reference": "cache off", "tls": "cache 16 MiB"},
              "cache_bytes": {"reference": 0, "tls": 16777216},
              "platform": platform.platform(), "rounds": args.rounds, "seconds_per_arm": args.duration,
              "server_threads": 8, "payload_bytes": 128, "block_bytes": 16384, "compression": "lz4",
              "qcache_max_bytes": 0, "docid_lookup_cache_size": args.docid_cache, "reader_tls": False, "reader_buffer_budget_bytes": 8388608,
              "calibration": {k: v for k, v in os.environ.items() if k.startswith("MANTICORE_")},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "binary": {"path": binary, "sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest()},
              "fixtures": {}, "cases": []}
    ctx = mp.get_context("spawn")
    initial_offset = args.order_offset
    for case in selected:
        fixture = args.fixtures / f"fixture-{case['docs']}"
        if not fixture.exists():
            print("building fixture", case["docs"], flush=True)
            make_fixture(binary, fixture, case["docs"])
        output["fixtures"][str(case["docs"])] = fixture_info(fixture, case["docs"])
        with tempfile.TemporaryDirectory(prefix="cache-toggle-") as temp, ExitStack() as stack:
            servers = {}
            for label, cache in output["cache_bytes"].items():
                folder = Path(temp) / label
                folder.mkdir()
                clone_data(fixture, folder)
                servers[label] = stack.enter_context(ReaderServer(binary, folder, cache, docid_cache=args.docid_cache).running())
            args.order_offset = (initial_offset + len(output["cases"])) % 2
            print("starting", case["name"], flush=True)
            entry = run_case(case, servers, ctx, args, query_sets=pools_for(case))
            for arm in entry["arms"].values():
                arm["rss_bytes_median"] = statistics.median(s["rss_bytes"] for s in arm["samples"])
            for label, db in servers.items():
                used = int(db.sql("SHOW STATUS LIKE 'docid_lookup_cache_used_bytes'")["data"][0]["Value"])
                assert 0 <= used <= args.docid_cache
                assert (used > 0) == (args.docid_cache > 0)
                entry["arms"][label]["docid_cache_used_bytes"] = used
                lifecycle(db, case["docs"])
            entry["lifecycle_checks_passed"] = True
            output["cases"].append(entry)
            args.output.write_text(json.dumps(output, indent=2) + "\n")
            print(f"{case['name']}: off {entry['arms']['reference']['qps_median']:.1f} -> "
                  f"on {entry['arms']['tls']['qps_median']:.1f} QPS "
                  f"({entry['qps_change_percent']:+.2f}%), CPU/query "
                  f"{entry['server_cpu_change_percent']:+.2f}%", flush=True)
    output["completed"] = True
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
