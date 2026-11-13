//
// Copyright (c) 2017-2026, Manticore Software LTD (https://manticoresearch.com)
// Copyright (c) 2001-2016, Andrew Aksyonoff
// Copyright (c) 2008-2016, Sphinx Technologies Inc
// All rights reserved
//
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License. You should have
// received a copy of the GPL license along with this program; if you
// did not, you can find it at http://www.gnu.org
//

// configuration generated from config_cmake.h.in template

#pragma once

/* Define to be the name of the compiler. */
#define COMPILER "AppleClang 21.0.0.21000101"

/* Full name OS */
#define OS_UNAME "Darwin arm64"

/* Flags used to configure me */
#define CONFIGURE_FLAGS "Configured with these definitions: -DUSE_SYSLOG=1 -DWITH_GALERA=OFF -DWITH_RE2=OFF -DWITH_STEMMER=OFF -DWITH_NLJSON=1 -DWITH_UNIALGO=1 -DWITH_ICU=1 -DWITH_ICU_FORCE_STATIC=0 -DWITH_JIEBA=OFF -DWITH_SSL=1 -DWITH_ZLIB=1 -DWITH_ZSTD=1 -DDL_ZSTD=1 -DZSTD_LIB=/opt/homebrew/opt/zstd/lib/libzstd.1.dylib -DWITH_CURL=1 -DWITH_ODBC=OFF -DWITH_EXPAT=1 -DWITH_ICONV=1 -DWITH_MYSQL=OFF -DWITH_POSTGRESQL=OFF -DLOCALDATADIR=/usr/local/var -DFULL_SHARE_DIR=/usr/local/share/manticore"

/* Define to 1 if you have the `backtrace' function. */
#define HAVE_BACKTRACE 1

/* Define to 1 if you have the `backtrace_symbols' function. */
#define HAVE_BACKTRACE_SYMBOLS 1

/* Define to 1 if you have the `clock_gettime' function. */
#define HAVE_CLOCK_GETTIME 1

/* Define to 1 if you have the `dlopen' function. Use header libutil.h to have all variants available */
#define HAVE_DLOPEN 1

/* Define if  you have async 'getaddrinfo_a' */
/* #undef HAVE_GETADDRINFO_A */

/* Define if  you have 'getrlimit' */
#define HAVE_GETRLIMIT 1

/* Define if  you have 'setrlimit' */
#define HAVE_SETRLIMIT 1

/* Define if your system supports the epoll system calls */
/* #undef HAVE_EPOLL */

/* Define if your system supports the kqueue system calls */
#define HAVE_KQUEUE 1

/* Define if your system supports the eventfd system calls */
#define HAVE_EVENTFD 0

/* Define if your system supports flag SO_REUSEPORT */
#define HAVE_SO_REUSEPORT 1

/* Define if your system libc has malloc_trim() */
#define HAVE_MALLOC_TRIM 0

/* Define if your system libc has malloc_stats() */
#define HAVE_MALLOC_STATS 0

/* Define if your system supports flag PTHREAD_RWLOCK_PREFER_WRITER_NONRECURSIVE_NP */
#define HAVE_RWLOCK_PREFER_WRITER 0

/* Define if F_SETLKW is defined in fcntl.h */
#define HAVE_F_SETLKW 1

/* Define to 1 if you have the `logf' function. */
#define HAVE_LOGF 1

/* Define to 1 if you have the 'mremap' function */
/* #undef HAVE_MREMAP */

/* Define to 1 if you have the `poll' function. */
#define HAVE_POLL 1

/* Define to 1 if you have the `pread' function. */
#define HAVE_PREAD 1

/* Define to 1 if you have the `pthread_mutex_timedlock' function. */
/* #undef HAVE_PTHREAD_MUTEX_TIMEDLOCK */

/* Define to 1 if you have the `pthread_cond_timedwait' function. */
#define HAVE_PTHREAD_COND_TIMEDWAIT 1

/* Define to 1 if you have the `pthread_getname_np' function. */
#define HAVE_PTHREAD_GETNAME_NP 1

/* Define to 1 if you have the `pthread_setname_np' function. */
/* #undef HAVE_PTHREAD_SETNAME_NP */

/* Define to 1 if you have the `pthread_setname_np' function. and it receive only 1 arg (name)*/
#define HAVE_PTHREAD_SETNAME_NP_1ARG 1

/* Define to 1 if you have the `strnlen' function. */
#define HAVE_STRNLEN 1

/* Whether we have internal atomic functions */
#define HAVE_SYNC_FETCH 1

/* define if mincore has unsigned 3-rd param */
/* #undef HAVE_UNSIGNED_MINCORE */

/* define to use POSIX Syslog for logging */
#define USE_SYSLOG 1

/* little-endian */
#define USE_LITTLE_ENDIAN (!0)

/* define to use Alexandresku's loki small obj allocator for movable attrs */
#define WITH_SMALLALLOC 0

/* Disable overriding of c++ memory routines */
#define DISABLE_MEMROUTINES 0

/* whether unaligned RAM access is possible */
#define UNALIGNED_RAM_ACCESS 1

/* name of replication lib - usually libgalera_manticore.so */
#define GALERA_SONAME ""

/* re2 library support */
#define WITH_RE2 0

/* libstemmer support */
#define WITH_STEMMER 0

/* ICU library support: "WITH" - feature available, "DL" - load dynamically, "LIB" - lib to load */
#define WITH_ICU 1
#define DL_ICU 0
/* #undef ICU_LIB */

/* Whether to use Jieba */
#define WITH_JIEBA 0

/* Whether to use OpenSSL */
#define WITH_SSL 1

/* define to use Zlib */
#define WITH_ZLIB 1

/* define to use Zstd */
#define WITH_ZSTD 1
#define DL_ZSTD 1
#define ZSTD_LIB "/opt/homebrew/opt/zstd/lib/libzstd.1.dylib"

/* define to use libcurl */
#define WITH_CURL 1
#define DL_CURL 0
/* #undef CURL_LIB */

/* default name of columnar shared library */
#define LIB_MANTICORE_COLUMNAR "lib_manticore_columnar.so"

/* default name of secondary index shared library */
#define LIB_MANTICORE_SECONDARY "lib_manticore_secondary.so"

/* default name of knn search shared library */
#define LIB_MANTICORE_KNN "lib_manticore_knn.so"

/* default name of knn embeddings shared library */
#define LIB_MANTICORE_KNN_EMBEDDINGS "lib_manticore_knn_embeddings.so"

/* define to set custom directory for shared files. Absolute as /usr/local/share/manticore */
#define FULL_SHARE_DIR "/usr/local/share/manticore"

/* define to set custom directory for shared files */
#define LOCALDATADIR "/usr/local/var"

/* define to set custom directory for shared files. Absolute as /etc */
#define SYSCONFDIR "/usr/local/etc/manticoresearch"

/* hardcoded default plugin dir */
#define HARDCODED_PLUGIN_DIR "/usr/local/lib/manticore"

/* define to set custom executor image version */
#define BUDDY_EXECUTOR_VERNUM "1.4.6"
