// Standalone experiments against the native cache, with untimed correctness
// checks. Each build selects its candidate header/implementation via include paths.
#include <docidlookupcache.h>
#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <random>
#include <string>
#include <vector>

static void Require ( bool b ) { if ( !b ) std::abort(); }

static uint64_t ThreadNS()
{
	timespec tTime;
	Require ( clock_gettime ( CLOCK_THREAD_CPUTIME_ID, &tTime )==0 );
	return uint64_t(tTime.tv_sec)*1000000000ULL+tTime.tv_nsec;
}

#ifdef DOCID_BATCH_PROBE
static void CheckBatch()
{
	for ( uint32_t nDocs : { 1, 64, 65, 1024, 1025, 16385 } )
	{
		auto pCache = DocidLookupCache_c::Create(nDocs);
		Require(bool(pCache));
		for ( uint32_t i=0; i<nDocs; ++i )
			Require ( pCache->Append ( i==nDocs-1 ? UINT64_MAX : uint64_t(i)*2+4, i ) );
		pCache->FindBatch ( nullptr, nullptr, 0 );
		uint64_t uQuery = UINT64_MAX;
		uint32_t uRow = 0;
		pCache->FindBatch ( &uQuery, &uRow, 1 );
		Require ( uRow==UINT32_MAX ); // unsealed input
		Require ( pCache->Seal() );
		for ( size_t nQueries : { 0, 1, 15, 16, 17, 31, 32, 33, 63, 64, 65, 1025 } )
		{
			std::mt19937_64 tRandom(42);
			std::vector<uint64_t> dQueries;
			for ( size_t i=0; i<nQueries; ++i )
			{
				uint64_t uID = (tRandom()%nDocs)*2+4+(i%2);
				if ( i%7==0 ) uID = UINT64_MAX;
				if ( i%7==1 ) uID = UINT64_MAX-1;
				if ( i%7==2 ) uID = 0;
				dQueries.push_back(uID);
			}
			std::vector<uint32_t> dRows(nQueries+2,42);
			pCache->FindBatch ( dQueries.data(), dRows.data()+1, nQueries );
			Require ( dRows.front()==42 && dRows.back()==42 );
			for ( size_t i=0; i<nQueries; ++i )
				Require ( dRows[i+1]==pCache->Find(dQueries[i]) );
		}
	}
}
#endif

int main ( int argc, char ** argv )
{
	const std::string sLabel = argc>1 ? argv[1] : "native";
	const std::string sOrder = argc>2 ? argv[2] : "random";
	const size_t nQueries = argc>3 ? std::stoul(argv[3]) : 131072;
	const bool bReverse = argc>4 && std::string(argv[4])=="reverse";
	Require ( nQueries && ( sOrder=="random" || sOrder=="sorted" ) );
	const size_t nPasses = std::max ( size_t(4), size_t(524288)/nQueries );
	DocidLookupCache_c::SetBudget ( 256*1024*1024 );
#ifdef DOCID_BATCH_PROBE
	CheckBatch();
#endif
	for ( uint32_t nDocs : { 100000, 1000000 } )
	{
		std::mt19937_64 tRandom(42);
		std::vector<std::pair<uint64_t,uint32_t>> dPairs;
		for ( uint32_t i=0; i<nDocs; ++i )
			dPairs.emplace_back ( tRandom() & 0x7ffffffffffffffeULL, i );
		std::sort ( dPairs.begin(), dPairs.end() );
		auto pCache = DocidLookupCache_c::Create(nDocs);
		Require(bool(pCache));
		for ( auto tPair : dPairs )
			Require ( pCache->Append ( tPair.first, tPair.second ) );
		Require ( pCache->Seal() );
		for ( int iMissPercent : { 0, 50, 100 } )
		{
			std::vector<uint64_t> dQueries;
			std::vector<uint32_t> dRows;
			uint64_t uExpected = 0;
			for ( size_t i=0; i<nQueries; ++i )
			{
				auto tPair = dPairs[tRandom()%nDocs];
				bool bMiss = int(tRandom()%100)<iMissPercent;
				dQueries.push_back(tPair.first+bMiss);
				dRows.push_back(bMiss ? UINT32_MAX : tPair.second);
				uExpected += dRows.back();
				Require ( pCache->Find(dQueries.back())==dRows.back() );
			}
			if ( sOrder=="sorted" )
			{
				std::vector<std::pair<uint64_t,uint32_t>> dSorted;
				for ( size_t i=0; i<nQueries; ++i )
					dSorted.emplace_back ( dQueries[i], dRows[i] );
				std::sort ( dSorted.begin(), dSorted.end() );
				for ( size_t i=0; i<nQueries; ++i )
				{
					dQueries[i] = dSorted[i].first;
					dRows[i] = dSorted[i].second;
				}
			}
			const auto dExpectedRows = dRows;
#ifdef DOCID_BATCH_PROBE
			constexpr int nModes = 2;
#else
			constexpr int nModes = 1;
#endif
			for ( int iRun=0; iRun<nModes; ++iRun )
			{
				const int iMode = bReverse ? nModes-iRun-1 : iRun;
				auto Work = [&] {
					uint64_t uSum = 0;
#ifdef DOCID_BATCH_PROBE
					if ( iMode )
					{
						pCache->FindBatch ( dQueries.data(), dRows.data(), dQueries.size() );
						for ( uint32_t uRow : dRows )
							uSum += uRow;
						return uSum;
					}
#endif
					for ( uint64_t uID : dQueries )
						uSum += pCache->Find(uID);
					return uSum;
				};
				Require ( Work()==uExpected );
				Require ( dRows==dExpectedRows );
				for ( int iSample=0; iSample<5; ++iSample )
				{
					uint64_t uSum = 0;
					auto tStart = ThreadNS();
					for ( size_t i=0; i<nPasses; ++i )
					{
						std::atomic_signal_fence(std::memory_order_seq_cst);
						uSum += Work();
					}
					auto tEnd = ThreadNS();
					Require ( uSum==uExpected*nPasses );
					double fNS = double(tEnd-tStart)/(dQueries.size()*nPasses);
					std::cout << sLabel << ',' << nDocs << ',' << iMissPercent << ',' << (iMode ? "batch" : "scalar")
						<< ',' << iSample << ',' << fNS << ',' << pCache->GetLengthBytes() << '\n';
				}
			}
		}
	}
	Require ( !DocidLookupCache_c::GetUsed() );
}
