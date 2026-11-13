# Independent reader TLS build

The source base is `047d2f99522d78e0aa1de7e7dc945a9abe1b673a` and the exact production patch is `tls.patch`, extracted from PR #5045 head `019868e9f79d1bb2bd1f96dafb88ef20acd45418`.

The same five PR reader tests were installed before building either arm:

```sh
git apply /path/to/evidence/common-test.patch
cp /path/to/evidence/gtests_docstore_readers.cpp src/gtests/
```

Source and build directories were separate. All 189 MCL files were verified against the upstream gitlink `88b5412a243ab0439957203acfe86c09944280d3`, including the standard Git archive substitutions in the version template. This build uses MCL APIs only, with no local columnar/secondary/KNN/embedding runtime build. No source or object files from the adaptive cache engine were reused.

Exact initial CMake options:

```sh
cmake -S /private/tmp/manticore-tls-independent-source-20261114 \
  -B /private/tmp/manticore-tls-independent-20261114/build \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O2 -DNDEBUG' \
  '-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O2 -DNDEBUG' \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DBUILD_TESTING=ON \
  -DWITH_BENCHES=OFF -DWITH_GALERA=OFF -DWITH_JIEBA=OFF \
  -DWITH_MYSQL=OFF -DWITH_ODBC=OFF -DWITH_POSTGRESQL=OFF \
  -DWITH_RE2=OFF -DWITH_STEMMER=OFF -DWITH_ICU=ON -DWITH_SSL=ON \
  -DMCL_LOCAL_RUNTIME=OFF \
  -DCACHEB=/Users/orca/Documents/GitHub/cache \
  -DLIBS_BUNDLE=/Users/orca/Documents/GitHub/bundle
cmake --build /private/tmp/manticore-tls-independent-20261114/build \
  --target searchd gmanticoretest -j8
```

The baseline binary, native test binary, native engine archive and SHA-256 hashes of all 299 object files were retained. Then `tls.patch` was applied, leaving Git HEAD at the same base revision, and the same build command was run again. Exactly one object changed: `src/CMakeFiles/lmanticore.dir/docstore.cpp.o`. The two LRU implementation files match upstream byte for byte.

The source tree is intentionally not a PR checkout with extra cache experiments. Common test registration is present in both arms; the only production-source change in the second arm is the saved TLS patch.

Native tests used isolated working directories, with `GTEST_DICT` pointing to `src/gtests`:

```sh
GTEST_DICT=/path/to/source/src/gtests /path/to/gtests-baseline
GTEST_DICT=/path/to/source/src/gtests /path/to/gtests-tls
/path/to/gtests-baseline --gtest_filter='DocstoreReadersTest.*' --gtest_repeat=20
/path/to/gtests-tls --gtest_filter='DocstoreReadersTest.*' --gtest_repeat=20
```

The benchmark driver applies the same saved stack-calibration environment to both arms. It clones fixture data with APFS copy-on-write and rewrites copied table registry paths, so neither server writes to the immutable fixtures. See the archived complete configurations, query hashes and test logs.
