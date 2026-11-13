#!/usr/bin/env python3
"""Count cache behavior separately from the size/budget performance matrix."""
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

from benchmark import ReaderServer, run_case
from scale_benchmark import SIZES, budgets, case_for, fixed_queries, fixture_info
from support import clone_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = {"diagnostic_only": True, "timing_values_discarded": True,
              "scope": "Counters include warmup and plan probes; reader admissions/query are derived from 256 stored-field accesses/query.",
              "cases": []}
    ctx = mp.get_context("spawn")
    for index, docs in enumerate(SIZES):
        source = args.fixtures / f"fixture-{docs}"
        chunks = fixture_info(source, docs)["disk_chunks"]
        pools = fixed_queries(docs)
        for cache in budgets(index, docs):
            with tempfile.TemporaryDirectory(prefix="pr5045-scale-diagnostic-") as temp:
                folder = Path(temp)
                clone_data(source, folder)
                case = case_for(docs, cache)
                with ReaderServer(str(args.binary.resolve()), folder, cache).running() as db:
                    run_case(case, {"reference": db, "tls": db}, ctx,
                             SimpleNamespace(rounds=2, duration=.25, order_offset=0), query_sets=pools)
                console = (folder / "console.log").read_text()
                values = re.findall(r"^READER_DIAGNOSTIC (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)$", console, re.M)
                assert len(values) == 1, console
                stats = dict(zip(("lookups", "tls_hits", "insertions", "deletions", "block_hits", "block_misses"), map(int, values[0])))
                total = stats["block_hits"] + stats["block_misses"]
                assert total % 256 == 0 and stats["lookups"] == stats["block_misses"]
                assert stats["insertions"] == stats["deletions"]
                stats["stored_field_queries"] = total // 256
                stats["locked_lookups"] = stats["lookups"] - stats["tls_hits"]
                stats["tls_hit_percent"] = 100 * stats["tls_hits"] / stats["lookups"] if stats["lookups"] else None
                stats["block_hit_percent"] = 100 * stats["block_hits"] / total
                stats["reader_admissions_per_query"] = stats["insertions"] / stats["stored_field_queries"]
                stats["disk_chunks"] = chunks
                output["cases"].append({"case": case, "counters": stats})
                args.output.write_text(json.dumps(output, indent=2) + "\n")
                print(case["name"], stats, flush=True)
    output["completed"] = True
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
