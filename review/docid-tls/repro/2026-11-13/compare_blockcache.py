#!/usr/bin/env python3
"""Compare block-cache variants with the same DocID budget and no reader TLS."""
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

from benchmark import ReaderServer, queries_for, run_case
from scale_benchmark import fixed_queries, fixture_info
from support import clone_data


def cases():
    result = []

    def add(name, docs=20000, cache=16777216, batch=256, clients=8, **extra):
        result.append(dict(name=name, docs=docs, cache=cache, batch=batch, clients=clients, **extra))

    add("small-off", cache=0)
    add("small-default")
    add("small-128m", cache=134217728)
    add("small-64", batch=64)
    add("small-point", batch=1)
    add("small-one-client", clients=1)
    add("small-count", count=True)
    add("small-aa", aa=True)
    add("100k-default", docs=100000)
    add("500k-default", docs=500000)
    add("1m-default", docs=1000000)
    add("1m-128m", docs=1000000, cache=134217728)
    add("1m-hot", docs=1000000, hot=True)
    add("5m-default", docs=5000000)
    add("5m-512m", docs=5000000, cache=536870912)
    add("5m-off", docs=5000000, cache=0)
    return result


def pools_for(case):
    if case["batch"] == 256 and not case.get("hot"):
        return fixed_queries(case["docs"], case.get("count", False))[:case["clients"]]
    return [queries_for(case["docs"], case["batch"], i, hot=case.get("hot", False))
            for i in range(case["clients"])]


def lifecycle(db, docs):
    db.sql("REPLACE INTO docs (id,body) VALUES (7,'replacement')")
    db.sql("FLUSH RAMCHUNK docs")
    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": "replacement"}]
    assert db.sql("SELECT count(*) AS n FROM docs")["data"] == [{"n": docs}]
    db.sql("DROP TABLE docs")
    db.sql("CREATE TABLE docs (body text stored)")
    db.sql("INSERT INTO docs (id,body) VALUES (7,'new table')")
    db.sql("FLUSH RAMCHUNK docs")
    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": "new table"}]


def selfcheck():
    matrix = cases()
    assert len(matrix) == len({c["name"] for c in matrix}) == 16
    assert all(c["cache"] == 16777216 for c in matrix if c["name"].endswith("default"))
    for c in matrix:
        pools = pools_for(c)
        assert len(pools) == c["clients"]
        assert all(len(expected) == (1 if c.get("count") else c["batch"])
                   for pool in pools for _, expected in pool)
    assert pools_for(matrix[1]) == fixed_queries(20000)
    assert pools_for(matrix[5]) == fixed_queries(20000)[:1]
    print("block-cache comparison selfcheck passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, nargs="?")
    parser.add_argument("candidate", type=Path, nargs="?")
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
    assert args.baseline and args.candidate and args.fixtures and args.output
    assert args.rounds >= 2 and args.duration > 0
    selected = [c for c in cases() if not args.cases or c["name"] in args.cases]
    assert selected and (not args.cases or len(selected) == len(args.cases))
    binaries = {"reference": str(args.baseline.resolve()), "tls": str(args.candidate.resolve())}
    output = {"comparison": "PR #5042 baseline vs block-cache candidate; same DocID budget, NO reader TLS",
              "arm_labels": {"reference": "baseline cache; see build manifest", "tls": "candidate cache; see build manifest"},
              "aa_note": "Both arms use the baseline binary for A/A cases.",
              "platform": platform.platform(), "rounds": args.rounds, "seconds_per_arm": args.duration,
              "qcache_max_bytes": 0, "docid_lookup_cache_size": args.docid_cache, "reader_tls": False, "reader_buffer_budget_bytes": 8388608,
              "payload_bytes": 128, "block_bytes": 16384, "compression": "lz4",
              "calibration": {k: v for k, v in os.environ.items() if k.startswith("MANTICORE_")},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "binaries": {k: {"path": v, "sha256": hashlib.sha256(Path(v).read_bytes()).hexdigest()}
                           for k, v in binaries.items()}, "fixtures": {}, "cases": []}
    ctx = mp.get_context("spawn")
    initial_offset = args.order_offset
    for case in selected:
        fixture = args.fixtures / f"fixture-{case['docs']}"
        assert fixture.is_dir(), fixture
        output["fixtures"][str(case["docs"])] = fixture_info(fixture, case["docs"])
        with tempfile.TemporaryDirectory(prefix="block-cache-compare-") as temp, ExitStack() as stack:
            servers = {}
            for label, binary in binaries.items():
                folder = Path(temp) / label
                folder.mkdir()
                clone_data(fixture, folder)
                binary = binaries["reference"] if case.get("aa") else binary
                servers[label] = stack.enter_context(ReaderServer(binary, folder, case["cache"], docid_cache=args.docid_cache).running())
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
            print(f"{case['name']}: {entry['arms']['reference']['qps_median']:.1f} -> "
                  f"{entry['arms']['tls']['qps_median']:.1f} QPS "
                  f"({entry['qps_change_percent']:+.2f}%), CPU/query "
                  f"{entry['server_cpu_change_percent']:+.2f}%", flush=True)
    output["completed"] = True
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
