# Independent Linux reader TLS build

The source base is `047d2f99522d78e0aa1de7e7dc945a9abe1b673a`; `tls.patch` is the exact production change from PR #5045 head `019868e9f79d1bb2bd1f96dafb88ef20acd45418`. The same five reader tests and CMake registration are applied before building either arm. MCL files come from the same upstream gitlink `88b5412a243ab0439957203acfe86c09944280d3` used by the independent Apple M4 build, with API-only configuration.

Build and execution take place in one isolated Ubuntu 24.04 container on native Linux/x86-64, with its task directory bind-mounted at `/work`. The host's production search services are not reconfigured. The benchmark only opens ephemeral loopback HTTP ports inside the task container. No host CPU governor, service, memory allocator or global page-cache setting is changed.

`build_pair.py` records the complete CMake command, dependencies, compiler version, compile commands, binary hashes and every object hash. Its CMake flags use Clang 18.1.3, `RelWithDebInfo` with explicit `-O2 -DNDEBUG`, and no `-march=native`. It disables Galera, Jieba, MySQL, ODBC, PostgreSQL, RE2 and stemmer; enables SSL and system ICU; disables the local MCL runtime. `searchd` and `gmanticoretest` are built with three parallel jobs. Ubuntu packages include CMake, Ninja, Clang, Boost context/filesystem, SSL, ICU, curl, zlib, LZ4, Zstd, Bison/Flex and GTest/GMock. Full installed versions are retained in `logs/packages.log`.

The baseline executables are copied aside, then only `tls.patch` is applied and the same build is run again. Both arms keep the same Git HEAD and generated version headers. `evidence/changed-objects.json` is checked by an assertion: only `src/CMakeFiles/lmanticore.dir/docstore.cpp.o` may differ. Both arms run the complete native suite, followed by all five reader tests with `--gtest_repeat=20`, in isolated working directories and with `GTEST_DICT=/work/source/src/gtests`.

Pinned source bundles are checked against the upstream CMake MD5 values; their SHA-256 hashes are also retained. Ubuntu GTest/GMock are shared by both arms. The source tree has no #5042 production changes.

The same 20k / 1M / 10M fixture files as the Apple M4 experiment are transferred to Linux. Only absolute paths in copied table-registry JSON files are rewritten. Original and imported fixture hashes are retained. Both binaries validate counts and exact first/middle/last stored values at every size before measurement; every timed query validates its full expected response.

The original `run_experiment.py` attempted the whole matrix and is retained as historical orchestration, not the final reproduction entry point. The final primary matrix has **19 complete comparisons using the original CPython HTTP client (1/8 clients), plus four complete 32-client comparisons using identical request bytes in a single write in both arms**. A 32-client HTTP timeout and a later connection reset interrupted earlier attempts. Those partial attempts and their logs are retained. The underlying failures remain unresolved; the matched transport variant does not establish that they are unrelated to TLS. No retry or ignored-error policy was added. Concurrency counts therefore do not form a transport-identical scaling curve.

The first 19 complete cases are unchanged from their original journals. `merge_results.py` checks the query-pool and timed CPU-accounting code against the original driver, binary hashes, six-round duration, and canonical case list before merging complete cases. `source_phase` and `driver_sha256` preserve each case's provenance. `diagnostics.json` retains 68 additional recorded timed samples from earlier complete/partial attempts and upstream A/A diagnostics. The four final 32-client cases contribute 48 primary samples; the main matrix has 276 samples in total. The telemetry-flagged cache-off 32-client point comparison was repeated in full once, adding 12 samples, without replacing the original. Total recorded samples: **356**.

An initial idle preflight produced zero timed samples because existing host services exceeded its stricter gate. Its original driver/plan/telemetry are retained. The subsequent co-resident-service protocol, idle gate and quality thresholds were fixed before the first timed sample; host services stayed enabled. No individual round was selected by performance. Timing did not overlap our compilation or native tests. Absolute-load flags do not establish balanced load between paired arms; the report includes the per-case balance audit.

The Python benchmark uses Linux process CPU accounting from `/proc/PID/stat` (100 Hz / 10 ms CPU ticks); it does not import the Apple experiment's stack-calibration environment. Fixture clones use `cp --reflink=auto -a` followed by JSON path rewrites. The telemetry module reads host-wide CPU totals and subtracts benchmark descendants, so it can see external CPU consumption even in the container's PID namespace. It does not access or print other processes' command-line arguments.

### Regenerate the saved report

From this artifact directory, with Python and Matplotlib installed:

```sh
python3 driver/make_linux_report.py merged report --repeat repeat
```

The renderer asserts journal/summary equality, all medians and deltas, lifecycle checks, binary identities and repeat query hashes. `report/summary.csv` contains the 23 main comparisons and one complete repeat; `report/samples.csv` contains all 356 recorded samples, including diagnostics.

### Run a fresh matched experiment

Use a **new** task directory mounted at `/work`; do not overwrite the saved evidence. The build script expects the pinned source/common-test snapshot, source-bundle archives and fixtures at the paths it records. Those large archives, executables and private MCL files are not embedded in this public evidence set. Source identities, hashes, the exact TLS/common-test patches and complete build configuration are included. The original source, binaries, toolchain container and fixtures are retained on the Linux host for a repeat.

```sh
python3 /work/build_pair.py
python3 /work/driver/run_tls.py --selfcheck
python3 /work/driver/load_telemetry.py
python3 /work/driver/selfcheck_warmup.py
python3 /work/driver/coalesced_http.py
python3 /work/reproduce.py --selfcheck
python3 /work/reproduce.py
```

`reproduce.py` runs the 19 original-client cases and four matched single-write cases sequentially, merges only complete comparisons, then repeats every flagged comparison once in full into `repeat-low` / `repeat-high`. It fails if a case errors; it does not silently substitute a different transport or retry. If a future run produces repeats, pass the applicable repeat directory to the report renderer with `--repeat`. The saved November 14 run used the historical directory name `repeat` for its one repeat.

`build_pair.py` and `merge_results.py` expect `/work`. The driver expects `searchd-baseline` and `searchd-tls` beside its `driver` directory. To rebuild fixtures instead of using the retained copies, use `benchmark.make_fixture()` with the baseline binary. That produces the same deterministic stored values and layout settings; physical chunk boundaries may differ. The benchmark uses only the Python standard library; chart regeneration additionally requires Matplotlib. Python 3.12 was used for measurement; the single-write client overrides a private CPython method and must be rechecked on Python upgrades.
