#!/usr/bin/env python3
"""Exercise separate diagnostic daemon; report counters, discard timing values."""
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

from benchmark import ReaderServer, cases, run_case
from support import clone_data

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("binary", type=Path)
parser.add_argument("fixtures", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()


def main():
    output = {"diagnostic_only": True, "timing_values_discarded": True,
              "scope": "Counters include query-plan probes, warmup and all checked requests; scheduling differs from timed binaries.",
              "cases": []}
    selected = {"resident-c8-b256", "large-c8-b256", "large-mixed", "nocache-c8-b256"}
    ctx = mp.get_context("spawn")
    for case in (c for c in cases() if c["name"] in selected):
        with tempfile.TemporaryDirectory(prefix="pr5045-diagnostic-") as temp:
            folder = Path(temp)
            clone_data(args.fixtures / f"fixture-{case['docs']}", folder)
            with ReaderServer(str(args.binary.resolve()), folder, case["cache"]).running() as db:
                run_case(case, {"reference": db, "tls": db}, ctx,
                         SimpleNamespace(rounds=2, duration=.25, order_offset=0))
            console = (folder / "console.log").read_text()
            values = re.findall(r"^READER_DIAGNOSTIC (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)$", console, re.M)
            assert len(values) == 1, console
            stats = dict(zip(("lookups", "tls_hits", "insertions", "deletions", "block_hits", "block_misses"), map(int, values[0])))
            stats["locked_lookups"] = stats["lookups"] - stats["tls_hits"]
            stats["tls_hit_percent"] = 100 * stats["tls_hits"] / stats["lookups"] if stats["lookups"] else None
            stats["block_hit_percent"] = 100 * stats["block_hits"] / (stats["block_hits"] + stats["block_misses"])
            assert stats["lookups"] == stats["block_misses"]
            assert stats["insertions"] == stats["deletions"]
            output["cases"].append({"case": case, "counters": stats})
            args.output.write_text(json.dumps(output, indent=2) + "\n")
            print(case["name"], stats, flush=True)


if __name__ == "__main__":
    main()
