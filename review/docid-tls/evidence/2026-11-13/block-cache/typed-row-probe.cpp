#include "/private/tmp/manticore-5042-cache-publish-20261113/src/docidlookupcache.h"
void probe(const DocidLookupCache_c &cache) { uint64_t ids[1] = {0}; char32_t rows[1]; cache.FindBatch(ids, rows, 1); }
