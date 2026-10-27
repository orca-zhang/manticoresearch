# Reproduction tools

These tools accompany the review package; they are not additional production
changes. Python tools use the standard library. Layout probes require C++17 and
POSIX thread CPU clocks (Linux/macOS). The server benchmarks use loopback ports,
temporary RT data and eight configured worker threads. Each client is a separate
process with a persistent HTTP connection; every returned field is checked.

## Independent patch checks

From this directory, with the base commit available in a Manticore checkout:

```sh
python3 verify_patches.py /path/to/manticoresearch --output /tmp/patch-checks.json
```

Both patches apply directly to
`047d2f99522d78e0aa1de7e7dc945a9abe1b673a`, separately and in either order.
Verification uses temporary Git indexes; it does not change the user's index,
working files, branch or commits. The resulting combined trees must be identical.

## TLS-only SQL comparison

Build an unmodified upstream baseline and save its `searchd` outside the build
directory. Apply `../patches/02-reader-tls.patch` and rebuild `searchd` and
`gmanticoretest`. Build dependencies/configuration follow upstream TESTING.md
and the compilation guide; one example is:

```sh
cmake -S /path/to/checkout -B /tmp/manticore-build \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON -DMCL_LOCAL_RUNTIME=OFF
cmake --build /tmp/manticore-build --target searchd gmanticoretest -j 6
cmake -E chdir /tmp/manticore-build src/gtests/gmanticoretest
```

Initialize `mcl` at the upstream superproject's pinned commit. No DocID prototype
or DocID-cache setting is required by `bench_reader_tls.py` or `support.py`.

```sh
python3 bench_reader_tls.py /path/to/before/searchd /path/to/tls/searchd \
  --output /tmp/reader-tls.json --block-size 16384 --compression lz4 --rounds 4
```

Default matrix: 20,000 rows, 128-byte stored text, 1/8 connections, 1/64/256 rows
per SELECT plus a count-only control; both block-cache budgets 0 and 16 MiB.
Four alternating two-second rounds per arm. Every JSON case records both query
plans, binary hashes, raw QPS, server CPU/query, client CPU and memory samples.
REPLACE/flush and drop/recreate checks run after timing. QPS is completed SQL
statements/second at fixed concurrency, not maximum sustainable capacity.

**Inside each comparison, the two arms always have the same block-cache budget.**
A positive ratio measures the TLS change at that budget; it does not measure a
benefit from disabling the block cache. A warmed block cache is a bypass control.
Do not compare absolute rates between separate runs or sum gains from two PRs.

On the local Apple build, both arms inherit the same supported `MANTICORE_*`
stack-calibration exports from that build's GoogleTest log. If this toolchain
requires those overrides, wrap the command with:

```sh
python3 run_with_calibration.py /path/to/this-build-gtests.log \
  python3 bench_reader_tls.py /path/to/before/searchd /path/to/tls/searchd \
  --output /tmp/reader-tls.json --block-size 16384 --compression lz4 --rounds 4
```

Never reuse the archived calibration as a portable default. Sanitized daemons
and diagnostic counters must not be used for timing. Keep builds/tests and other
benchmark workloads stopped during timed comparisons.

## Cache-line directory isolation

```sh
python3 bench_cache_layout.py --output /tmp/docid-layout --rounds 5 --opt-level 3
python3 bench_cache_layout.py --output /tmp/docid-current --rounds 5 --opt-level 3 \
  --candidate /path/to/patched/checkout/src
```

The saved `fixed16` and `adaptive` source pairs match the measured directory
experiment; both use stack scratch. `--candidate` compiles the current module
unchanged. Matching headers/sources are compiled separately to avoid ODR mixing.
The runner checks results before timing, rotates order and splits batch calls
into 16 probes, with sorted pools of 1,000 and random pools of 131,072. It records
compiler commands/source hashes and raw thread CPU ns per lookup. A CXX override
selects the compiler. Use `--opt-level 2` for the reported Apple optimization.
`--compile-only` is a build smoke check, not a performance result.

The original archived experiment rotated a third, historical scratch-TLS arm.
The PR comparison selects only `auto` (fixed16 + stack) and `adaptive-stack`
from those raw CSVs. The compact runner here reproduces those two mechanisms;
its scheduling order is not byte-for-byte the original three-arm run. The
sources and metric remain explicit. Throughput gain is
`median(fixed16 ns) / median(adaptive ns) - 1`; it is not SQL QPS.

## DocID SQL lifecycle

Apply patch 1, build `searchd`/`gmanticoretest`, run the full GoogleTest suite, then:

```sh
python3 /path/to/patched/checkout/test/docid-cache/test_integration.py \
  /path/to/patched/checkout/build/src/searchd
```

This explicitly runs the standalone SQL lifecycle regression at disabled,
refused and admitted budgets. It is not automatically registered with CTest.
The core/reader/planner C++ tests are registered through the existing GoogleTest
CMake target. Full UberTest/CLT and platform CI are separate upstream checks.

## Focused sanitizers

With GoogleTest available, the cache is independently buildable with C++17.
Compile `src/docidlookupcache.cpp` and `src/gtests/gtests_docidcache.cpp` with
`-fsanitize=address,undefined -fno-omit-frame-pointer -O1 -g`, the source include
path and your GoogleTest include/library paths; link `gtest_main`, `gtest` and
thread support. Run the resulting tests. For concurrent diagnostics, use a
separate `-fsanitize=thread` build. Never combine TSan with ASan.

For a Unix Makefiles engine build including patch 2 and its test target:

```sh
python3 sanitize_readers.py /path/to/checkout /path/to/checkout/build \
  --output /tmp/readers-asan --sanitizer address,undefined --repeat 20
python3 sanitize_readers.py /path/to/checkout /path/to/checkout/build \
  --output /tmp/readers-tsan --sanitizer thread --repeat 20
```

The helper instruments docstore.cpp, fileio.cpp and the reader tests and reuses
other built engine objects/libraries. This is focused coverage, not a complete
engine sanitizer build. The archived earlier logs describe their actual scope.
The portable helper was syntax/CLI-checked in this preparation; historical
sanitizer success is recorded for the original local commands/source hashes.
