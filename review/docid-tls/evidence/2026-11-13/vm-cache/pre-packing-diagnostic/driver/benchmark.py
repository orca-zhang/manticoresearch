#!/usr/bin/env python3
"""TLS-only paired SQL benchmarks; synthetic loopback data, standard library only."""
import argparse
from contextlib import ExitStack
import hashlib
import http.client
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import tempfile
import time
import urllib.parse

from support import Server, TIMEBASE, clone_data, resources


def value(docid, size=128):
    return (f"row{docid:08d}:" + "abcdefghijklmnopqrstuvwxyz" * ((size + 25) // 26))[:size]


class ReaderServer(Server):
    def __init__(self, binary, root, cache, docid_cache=None):
        super().__init__(binary, root, threads=8)
        self.config.write_text(self.config.read_text().replace(
            "buddy_path =\n", f"buddy_path =\ndocstore_cache_size = {cache}\nqcache_max_bytes = 0\n"))
        if docid_cache is not None:
            self.config.write_text(self.config.read_text().replace(
                "buddy_path =\n", f"buddy_path =\ndocid_lookup_cache_size = {docid_cache}\n"))


def queries_for(docs, batch, worker, count=False, hot=False):
    rng = random.Random(5045 + worker * 1009 + batch)
    queries = []
    # A single-client point workload must also touch more than 16 MiB of blocks.
    for _ in range(4096 if batch == 1 and not hot else 64):
        ids = sorted(rng.sample(range(1, min(docs, 4096) + 1) if hot else range(1, docs + 1), batch))
        clause = ",".join(map(str, ids))
        sql = (f"SELECT count(*) AS n FROM docs WHERE id IN ({clause})" if count else
               f"SELECT id,body FROM docs WHERE id IN ({clause}) ORDER BY id ASC LIMIT {batch}")
        expected = [{"n": batch}] if count else [{"id": i, "body": value(i)} for i in ids]
        queries.append((urllib.parse.urlencode({"query": sql}).encode(), expected))
    return queries


def init_worker(go, ready):
    global GO, READY
    GO, READY = go, ready


def execute(connection, query):
    body, expected = query
    connection.request("POST", "/sql?mode=raw", body,
                       {"Content-Type": "application/x-www-form-urlencoded", "Connection": "keep-alive"})
    response = connection.getresponse()
    reply = json.loads(response.read())
    assert response.status == 200 and all(not item.get("error") for item in reply), reply
    assert reply[0]["data"] == expected, (reply, expected)
    assert not response.will_close


def worker(port, queries, duration, reconnect, rate_limit):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    for query in queries:
        execute(connection, query)
    connection.close()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    READY.put(True)
    GO.wait()
    started, cpu = time.perf_counter(), time.process_time_ns()
    completed, latencies = 0, []
    while time.perf_counter() - started < duration:
        before = time.perf_counter_ns()
        execute(connection, queries[completed % len(queries)])
        if reconnect:
            connection.close()
        latencies.append(time.perf_counter_ns() - before)
        completed += 1
        if rate_limit:
            time.sleep(max(0, started + completed / rate_limit - time.perf_counter()))
    finished, cpu = time.perf_counter(), time.process_time_ns() - cpu
    connection.close()
    return {"completed": completed, "finished": finished, "client_cpu_ns": cpu,
            "latencies_ns": latencies}


def cases():
    result = []
    def add(name, docs=1000000, cache=16777216, clients=8, batch=256, **extra):
        result.append(dict(name=name, docs=docs, cache=cache, clients=clients, batch=batch, **extra))
    for batch in (1, 64, 256):
        add(f"resident-c8-b{batch}", docs=20000, batch=batch)
    add("resident-count", docs=20000, count=True)
    for clients in (1, 8):
        for batch in (1, 64, 256):
            add(f"large-c{clients}-b{batch}", clients=clients, batch=batch)
        add(f"large-c{clients}-count", clients=clients, count=True)
    add("large-hot", hot=True)
    add("large-mixed", mixed=True)
    # Keep TIME_WAIT sockets below the host's ephemeral-port budget.
    add("large-reconnect", batch=1, reconnect=True, rate_limit=50)
    for batch in (1, 64, 256):
        add(f"nocache-c8-b{batch}", cache=0, batch=batch)
    add("nocache-count", cache=0, count=True)
    add("aa-large-b256", aa=True)
    return result


def quantile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def summarize(entry):
    for arm in entry["arms"].values():
        for metric in ("qps", "server_cpu_ms_per_query", "p50_ms", "p95_ms", "p99_ms"):
            arm[metric + "_median"] = statistics.median(s[metric] for s in arm["samples"])
    before, after = entry["arms"]["reference"], entry["arms"]["tls"]
    for metric, key in (("qps", "qps_change_percent"),
                        ("server_cpu_ms_per_query", "server_cpu_change_percent"),
                        ("p95_ms", "p95_change_percent")):
        entry[key] = (after[metric + "_median"] / before[metric + "_median"] - 1) * 100
    entry["paired_qps_changes_percent"] = [
        (a["qps"] / b["qps"] - 1) * 100
        for b, a in zip(before["samples"], after["samples"])]
    if entry["case"].get("mixed"):
        entry["group_qps_change_percent"] = {
            group: (statistics.median(s["group_qps"][group] for s in after["samples"]) /
                    statistics.median(s["group_qps"][group] for s in before["samples"]) - 1) * 100
            for group in ("bulk256", "hotpoint")}


def make_fixture(binary, folder, docs):
    folder.mkdir()
    with ReaderServer(binary, folder, 0).running() as db:
        db.sql("CREATE TABLE docs (body text stored) engine='rowwise' "
               "docstore_block_size='16384' docstore_compression='lz4'")
        for start in range(1, docs + 1, 1000):
            rows = ",".join(f"({i},'{value(i)}')" for i in range(start, min(start + 1000, docs + 1)))
            db.sql("INSERT INTO docs (id,body) VALUES " + rows)
        db.sql("FLUSH RAMCHUNK docs")
        assert db.sql("SELECT count(*) AS n FROM docs")["data"] == [{"n": docs}]
    return {"logical_stored_text_bytes": docs * 128,
            "disk_bytes": sum(p.stat().st_size for p in (folder / "data").rglob("*") if p.is_file()),
            "spds_bytes": sum(p.stat().st_size for p in (folder / "data").rglob("*.spds"))}


def run_case(case, servers, ctx, args, query_sets=None):
    entry = {"case": case, "arms": {label: {"samples": []} for label in servers}}
    if query_sets is None:
        query_sets = []
        for index in range(case["clients"]):
            bulk = case.get("mixed") and index < case["clients"] // 2
            point = case.get("mixed") and not bulk
            query_sets.append(queries_for(case["docs"], 1 if point else case["batch"], index,
                                          count=case.get("count", False), hot=case.get("hot", False) or point))
    entry["query_pool_sizes"] = [len(q) for q in query_sets]
    entry["query_set_sha256"] = hashlib.sha256(b"\n".join(q[0] for qs in query_sets for q in qs)).hexdigest()
    for label, db in servers.items():
        sql = urllib.parse.parse_qs(query_sets[0][0][0].decode())["query"][0]
        entry["arms"][label]["meta"] = db.sql_all(sql + "; SHOW META")[1]["data"]
    go, ready = ctx.Event(), ctx.Queue()
    with ctx.Pool(case["clients"], initializer=init_worker, initargs=(go, ready)) as pool:
        for repeat in range(args.rounds):
            labels = list(servers)
            if (repeat + args.order_offset) % 2:
                labels.reverse()
            for label in labels:
                db = servers[label]
                go.clear()
                jobs = [pool.apply_async(worker, (db.port, queries, args.duration, case.get("reconnect", False), case.get("rate_limit")))
                        for queries in query_sets]
                for _ in jobs:
                    ready.get(timeout=180)
                before = resources(db.pid)
                started = time.perf_counter()
                go.set()
                replies = [job.get(timeout=args.duration + 30) for job in jobs]
                after = resources(db.pid)
                elapsed = max(r["finished"] for r in replies) - started
                completed = sum(r["completed"] for r in replies)
                latency = [n for reply in replies for n in reply["latencies_ns"]]
                sample = {"round": repeat, "order": labels, "completed": completed,
                          "elapsed_seconds": elapsed, "qps": completed / elapsed,
                          "server_cpu_ms_per_query": (after["cpu_ns"] - before["cpu_ns"]) / 1e6 / completed,
                          "client_cpu_cores": sum(r["client_cpu_ns"] for r in replies) / 1e9 / elapsed,
                          "rss_bytes": after["rss_bytes"],
                          "p50_ms": quantile(latency, .50) / 1e6,
                          "p95_ms": quantile(latency, .95) / 1e6,
                          "p99_ms": quantile(latency, .99) / 1e6}
                if case.get("mixed"):
                    split = case["clients"] // 2
                    sample["group_qps"] = {
                        "bulk256": sum(r["completed"] for r in replies[:split]) / elapsed,
                        "hotpoint": sum(r["completed"] for r in replies[split:]) / elapsed}
                entry["arms"][label]["samples"].append(sample)
    summarize(entry)
    return entry


def selfcheck():
    assert len({c["name"] for c in cases()}) == len(cases()) == 20
    assert queries_for(1000000, 1, 0) == queries_for(1000000, 1, 0)
    point_ids = {q[1][0]["id"] for q in queries_for(1000000, 1, 0)}
    assert len(point_ids) > 4000 and max(point_ids) > 990000
    assert all(row["id"] <= 4096 for _, expected in queries_for(1000000, 256, 0, hot=True) for row in expected)
    fake = {"case": {}, "arms": {
        "reference": {"samples": [dict(qps=100, server_cpu_ms_per_query=2, p50_ms=1, p95_ms=2, p99_ms=3)]},
        "tls": {"samples": [dict(qps=110, server_cpu_ms_per_query=1, p50_ms=1, p95_ms=1, p99_ms=2)]}}}
    summarize(fake)
    assert abs(fake["qps_change_percent"] - 10) < 1e-9 and fake["server_cpu_change_percent"] == -50
    print("harness selfcheck passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="?", type=Path)
    parser.add_argument("tls", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--order-offset", type=int, default=0)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    assert args.reference and args.tls and args.output and args.work
    assert args.rounds >= 2 and args.duration > 0
    selected = [c for c in cases() if args.cases is None or c["name"] in args.cases]
    assert selected and (args.cases is None or len(selected) == len(args.cases))
    binaries = {"reference": str(args.reference.resolve()), "tls": str(args.tls.resolve())}
    output = {"platform": platform.platform(), "compiler": "Apple Clang 21, -O2 -DNDEBUG; debug symbols omitted",
              "upstream_base": "047d2f99522d78e0aa1de7e7dc945a9abe1b673a",
              "tls_commit": "019868e9f79d1bb2bd1f96dafb88ef20acd45418",
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rounds": args.rounds, "seconds_per_arm": args.duration, "server_threads": 8,
              "block_bytes": 16384, "compression": "lz4", "payload_bytes": 128,
              "cpu_timebase": {"numer": TIMEBASE.numer, "denom": TIMEBASE.denom},
              "calibration": {k: v for k, v in os.environ.items() if k.startswith("MANTICORE_")},
              "binaries": {k: {"path": v, "sha256": hashlib.sha256(Path(v).read_bytes()).hexdigest()}
                           for k, v in binaries.items()}, "fixtures": {}, "cases": []}
    args.work.mkdir(parents=True, exist_ok=True)
    ctx = mp.get_context("spawn")
    for docs in dict.fromkeys(c["docs"] for c in selected):
        fixture = args.work / f"fixture-{docs}"
        if not fixture.exists():
            print(f"building fixture: {docs} rows", flush=True)
            output["fixtures"][str(docs)] = make_fixture(binaries["reference"], fixture, docs)
        else:
            output["fixtures"][str(docs)] = {
                "logical_stored_text_bytes": docs * 128,
                "disk_bytes": sum(p.stat().st_size for p in (fixture / "data").rglob("*") if p.is_file()),
                "spds_bytes": sum(p.stat().st_size for p in (fixture / "data").rglob("*.spds"))}
        for cache in dict.fromkeys(c["cache"] for c in selected if c["docs"] == docs):
            with tempfile.TemporaryDirectory(prefix="arms-", dir=args.work) as temp, ExitStack() as stack:
                servers = {}
                for label, binary in binaries.items():
                    folder = Path(temp) / label
                    folder.mkdir()
                    clone_data(fixture, folder)
                    servers[label] = stack.enter_context(ReaderServer(binary, folder, cache).running())
                for case in (c for c in selected if c["docs"] == docs and c["cache"] == cache):
                    if case.get("aa"):
                        folder = Path(temp) / "aa"
                        folder.mkdir()
                        clone_data(fixture, folder)
                        aa = stack.enter_context(ReaderServer(binaries["reference"], folder, cache).running())
                        used_servers = {"reference": servers["reference"], "tls": aa}
                    else:
                        used_servers = servers
                    print(f"starting {case['name']}", flush=True)
                    entry = run_case(case, used_servers, ctx, args)
                    output["cases"].append(entry)
                    args.output.write_text(json.dumps(output, indent=2) + "\n")
                    print(f"{case['name']}: QPS {entry['qps_change_percent']:+.2f}% "
                          f"CPU/query {entry['server_cpu_change_percent']:+.2f}% "
                          f"p95 {entry['p95_change_percent']:+.2f}%", flush=True)
                for db in servers.values():
                    db.sql("REPLACE INTO docs (id,body) VALUES (7,'replacement')")
                    db.sql("FLUSH RAMCHUNK docs")
                    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": "replacement"}]
                    assert db.sql("SELECT count(*) AS n FROM docs")["data"] == [{"n": docs}]
                    db.sql("DROP TABLE docs")
                    db.sql("CREATE TABLE docs (body text stored)")
                    db.sql("INSERT INTO docs (id,body) VALUES (7,'new table')")
                    db.sql("FLUSH RAMCHUNK docs")
                    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": "new table"}]
    output["lifecycle_checks_passed"] = True
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
