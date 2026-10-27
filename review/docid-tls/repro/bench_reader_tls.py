#!/usr/bin/env python3
"""Paired stored-field SQL QPS for the shared-map reader TLS front cache.

Uses identical disk snapshots, eight server workers, alternating sequential
arms and one client process per persistent HTTP connection. Validates every
returned stored field. Cache-disabled cases exercise reader lookups; warmed
16 MiB cases and count-only queries are controls. No diagnostic counters are
included in measured binaries.
"""
import argparse
from contextlib import ExitStack
import hashlib
import http.client
import json
import multiprocessing as mp
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
import urllib.parse

from support import resources, TIMEBASE, clone_data, Server


class ReaderServer(Server):
    def __init__(self, binary, root, block_cache):
        super().__init__(binary, root, threads=8)
        self.config.write_text(self.config.read_text().replace(
            "buddy_path =\n", f"buddy_path =\ndocstore_cache_size = {block_cache}\n"))


def value(docid, size):
    return (f"row{docid:08d}:" + "abcdefghijklmnopqrstuvwxyz" * ((size + 25) // 26))[:size]


def init_worker(go, ready):
    global GO, READY
    GO, READY = go, ready


def check_reply(connection, body, expected):
    connection.request("POST", "/sql?mode=raw", body, {
        "Content-Type": "application/x-www-form-urlencoded", "Connection": "keep-alive"})
    response = connection.getresponse()
    data = json.loads(response.read())
    assert response.status == 200 and all(not item.get("error") for item in data), data
    assert data[0]["data"] == expected, (data, expected)
    assert not response.will_close


def worker(port, queries, duration):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    for body, expected in queries:
        check_reply(connection, body, expected)
    READY.put(True)
    GO.wait()
    started, cpu_start = time.perf_counter(), time.process_time_ns()
    completed = 0
    while time.perf_counter() - started < duration:
        check_reply(connection, *queries[completed % len(queries)])
        completed += 1
    cpu_ns = time.process_time_ns() - cpu_start
    connection.close()
    return {"completed": completed, "client_cpu_ns": cpu_ns}


def queries_for(docs, concurrency, batch, payload, count_only):
    rng = random.Random(257 + batch)
    result = []
    for _ in range(concurrency):
        queries = []
        for _ in range(20):
            ids = sorted(rng.sample(range(1, docs + 1), batch))
            clause = ",".join(map(str, ids))
            if count_only:
                query = f"SELECT count(*) AS n FROM docs WHERE id IN ({clause})"
                expected = [{"n": batch}]
            else:
                query = f"SELECT id,body FROM docs WHERE id IN ({clause}) ORDER BY id ASC LIMIT {batch}"
                expected = [{"id": docid, "body": value(docid, payload)} for docid in ids]
            queries.append((urllib.parse.urlencode({"query": query}).encode(), expected))
        result.append(queries)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=lambda v: str(Path(v).resolve()))
    parser.add_argument("tls", type=lambda v: str(Path(v).resolve()))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docs", type=int, default=20000)
    parser.add_argument("--payload", type=int, default=128)
    parser.add_argument("--block-size", type=int, default=1024)
    parser.add_argument("--compression", choices=["none", "lz4"], default="none")
    parser.add_argument("--block-caches", nargs="+", type=int, default=[0, 16 * 1024 * 1024])
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 8])
    parser.add_argument("--batches", nargs="+", type=int, default=[1, 64, 256])
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    assert args.docs >= max(args.batches) and args.duration > 0 and args.rounds > 0
    binaries = {"reference": args.reference, "tls": args.tls}
    output = {"platform": sys.platform, "docs": args.docs, "payload_bytes": args.payload,
              "block_size": args.block_size, "compression": args.compression,
              "server_threads": 8, "docid_prototype": False, "rounds": args.rounds, "seconds_per_arm": args.duration,
              "cpu_timebase": {"numer": TIMEBASE.numer, "denom": TIMEBASE.denom} if TIMEBASE else None,
              "client": "one process per persistent HTTP connection; every result checked",
              "binaries": {label: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                           for label, path in binaries.items()}, "cases": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="manticore-reader-qps-") as temp:
        root = Path(temp)
        fixture = root / "fixture"
        fixture.mkdir()
        with ReaderServer(args.reference, fixture, 0).running() as db:
            db.sql(f"CREATE TABLE docs (body text stored) engine='rowwise' "
                   f"docstore_block_size='{args.block_size}' docstore_compression='{args.compression}'")
            for start in range(1, args.docs + 1, 1000):
                rows = ",".join(f"({i},'{value(i, args.payload)}')" for i in range(start, min(start + 1000, args.docs + 1)))
                db.sql("INSERT INTO docs (id,body) VALUES " + rows)
            db.sql("FLUSH RAMCHUNK docs")
        for block_cache in args.block_caches:
            with ExitStack() as stack:
                servers = {}
                for label, binary in binaries.items():
                    folder = root / f"cache-{block_cache}-{label}"
                    folder.mkdir()
                    clone_data(fixture, folder)
                    servers[label] = stack.enter_context(ReaderServer(binary, folder, block_cache).running())
                ctx = mp.get_context("spawn")
                for concurrency in args.concurrency:
                    go, ready = ctx.Event(), ctx.Queue()
                    with ctx.Pool(concurrency, initializer=init_worker, initargs=(go, ready)) as pool:
                        for batch, count_only in [(n, False) for n in args.batches] + [(max(args.batches), True)]:
                            queries = queries_for(args.docs, concurrency, batch, args.payload, count_only)
                            entry = {"block_cache_bytes": block_cache, "concurrency": concurrency,
                                     "batch": batch, "count_only": count_only,
                                     "arms": {label: {"samples": []} for label in servers}}
                            plan_sql = urllib.parse.parse_qs(queries[0][0][0].decode())["query"][0]
                            for label, db in servers.items():
                                meta = db.sql_all(plan_sql + "; SHOW META")[1]["data"]
                                entry["arms"][label]["plan"] = [row for row in meta if "index" in str(row).lower()]
                            for repeat in range(args.rounds):
                                labels = list(servers)
                                if (repeat + len(output["cases"])) % 2:
                                    labels.reverse()
                                for label in labels:
                                    db = servers[label]
                                    go.clear()
                                    jobs = [pool.apply_async(worker, (db.port, item, args.duration)) for item in queries]
                                    for _ in jobs:
                                        ready.get(timeout=30)
                                    before = resources(db.pid)
                                    started = time.perf_counter()
                                    go.set()
                                    replies = [job.get(timeout=30) for job in jobs]
                                    elapsed = time.perf_counter() - started
                                    after = resources(db.pid)
                                    completed = sum(reply["completed"] for reply in replies)
                                    entry["arms"][label]["samples"].append({
                                        "completed": completed, "elapsed_seconds": elapsed,
                                        "qps": completed / elapsed,
                                        "server_cpu_ms_per_query": (after["cpu_ns"] - before["cpu_ns"]) / 1e6 / completed,
                                        "client_cpu_cores": sum(reply["client_cpu_ns"] for reply in replies) / 1e9 / elapsed,
                                        "rss_bytes": after["rss_bytes"],
                                        "footprint_bytes": after.get("footprint_bytes")})
                            for arm in entry["arms"].values():
                                for metric in ("qps", "server_cpu_ms_per_query"):
                                    arm[metric + "_median"] = statistics.median(s[metric] for s in arm["samples"])
                            entry["qps_gain_percent"] = (entry["arms"]["tls"]["qps_median"] / entry["arms"]["reference"]["qps_median"] - 1) * 100
                            entry["server_cpu_change_percent"] = (entry["arms"]["tls"]["server_cpu_ms_per_query_median"] / entry["arms"]["reference"]["server_cpu_ms_per_query_median"] - 1) * 100
                            output["cases"].append(entry)
                            args.output.write_text(json.dumps(output, indent=2) + "\n")
                            print(f"cache={block_cache} clients={concurrency} batch={batch} count={count_only}: "
                                  f"QPS {entry['qps_gain_percent']:+.2f}% CPU/query {entry['server_cpu_change_percent']:+.2f}%", flush=True)
                for db in servers.values():
                    replacement = "replacement"
                    db.sql(f"REPLACE INTO docs (id,body) VALUES (7,'{replacement}')")
                    db.sql("FLUSH RAMCHUNK docs")
                    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": replacement}]
                    assert db.sql("SELECT count(*) AS n FROM docs")["data"] == [{"n": args.docs}]
                    db.sql("DROP TABLE docs")
                    db.sql("CREATE TABLE docs (body text stored)")
                    db.sql("INSERT INTO docs (id,body) VALUES (7,'new table')")
                    db.sql("FLUSH RAMCHUNK docs")
                    assert db.sql("SELECT body FROM docs WHERE id=7")["data"] == [{"body": "new table"}]
        output["lifecycle_checks_passed"] = True
        args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
