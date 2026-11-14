# Reproduction

The measured cache implementation is `8fec92b21c2f10f720f0bcbca498c5f8179f7ac0`.
The latest head is `d89cebcdbee5eeaa205b6a861067b0d1219e6ea3`: `docstore_cache=1`
enables adaptive caching by default, `docstore_cache=0` disables it, and
`docstore_cache_size` remains the ceiling (default 16 MiB; zero disables).
The adaptive algorithms match the measured build; configuration wiring changed.
`configuration-identity.json` hashes the matching algorithm/test sources.
`configuration-switch.patch` records the follow-up over `90e8841`, and
`latest-full-pr.patch` records the complete current source diff.
The earlier `source.patch`, `full-pr.patch` and `publish-identity.json` retain
their original dated targets; they are not overwritten with new source claims.

The complete source patch is relative to upstream `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`.

## Build and checks

Use the repository's documented dependencies and Apple Clang 21 on macOS.
`build-settings.json` records compiler paths, options, flags and generator;
`validation/configure.log` records dependency/configuration output. The main
CMake arguments are also recorded as an array in `configure-arguments.json`
so spaces in optimization flags remain unambiguous. Build `searchd` and
`gmanticoretest`. Run the native executable with `GTEST_DICT` pointing to
the checkout's `src/gtests`, and the API smoke test with:

```sh
ctest --test-dir build -R 'Perform API smoke test' --output-on-failure
python3 test/docid-cache/test_integration.py build/src/searchd
```

`check_sanitizers.py` retains the focused ASan+UBSan and TSan build/run commands.
It reuses this run's build/dependency paths; adjust the source/build constants
for a new checkout. The recorded sanitizer scope is not a fully instrumented engine.

## Fresh measurements

Place the measured `8fec92b` build's executable at `./searchd`, beside `run_final.py`.
The recorded fixed-policy reference arms require that measured revision; the
latest server exposes adaptive/off only. Its enable switch is checked separately
with `python3 configuration-test/test_blockcache_config.py /path/to/latest/searchd`.
These standard-library benchmark drivers use macOS Mach CPU/memory telemetry.
Large immutable data fixtures are generated on first run; they and executable
binaries are intentionally omitted. Keep adequate disk space for the 20M-row
fixture and APFS clones. Do not run the following commands concurrently:

```sh
python3 run_final.py --selfcheck
python3 run_final.py
python3 run_controls.py
```

The first command checks query sizes and balanced ordering. The matrix records
the exact script/binary hashes and each arm's config before timing. It checks
every timed response and exercises REPLACE/flush/drop/recreate afterward.
DocID and SQL query caches are zero. Original outputs are in `raw/` and will
not be overwritten by the default fresh-run output directories.

The original 100k-row case triggered the pre-recorded complete-repeat rule.
Its full confirmation command was:

```sh
python3 run_final.py --rows 100000 --skip-memory --output confirm-100000
```

Both complete series are preserved; no individual round was removed. The
memory diagnostics have two passes with reversed fixed/adaptive order;
the second fixed pass also provides an independent repetition of the first.
Memory-sampler throughput is not pooled into the primary QPS tables.

## Regenerate the preserved tables and figures

Use a Python environment with Matplotlib:

```sh
python3 summarize.py raw regenerated
python3 write_docs.py . regenerated
```

`summarize.py` asserts journal/result equality, six samples per arm, median
arithmetic, shared binary identity and completed lifecycle checks. The archive's
`MANIFEST.json` gives a SHA-256 for every file except itself.
