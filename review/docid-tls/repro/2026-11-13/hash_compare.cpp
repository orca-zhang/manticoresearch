// Isolated scalar-key hash probe; this is not a SQL throughput benchmark.
#include "std/hash.h"
#include "std/crc32.h"

#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <string>
#include <unordered_set>
#include <vector>

struct ProbeKey_t { uint64_t m_uIndex, m_uOffset; };

struct CRC_t
{
	static uint32_t Hash ( const ProbeKey_t & k )
	{
		return sphCRC32 ( &k.m_uOffset, sizeof(k.m_uOffset), sphCRC32 ( &k.m_uIndex, sizeof(k.m_uIndex) ) );
	}
};

struct XXH_t
{
	static uint32_t Hash ( const ProbeKey_t & k ) { return uint32_t ( HashWithSeed ( &k.m_uOffset, sizeof(k.m_uOffset), k.m_uIndex ) ); }
};

template <uint32_t SEED> struct BKDR_t
{
	static uint32_t Hash ( const ProbeKey_t & k )
	{
		uint32_t uHash = 0;
		for ( uint64_t uPart : { k.m_uIndex, k.m_uOffset } )
			for ( int i=0; i<8; ++i ) uHash = uHash*SEED + uint8_t(uPart>>(8*i));
		return uHash;
	}
};

struct BKDRFold_t
{
	static uint32_t Hash ( const ProbeKey_t & k ) { auto h = BKDR_t<131>::Hash(k); return h^(h>>16); }
};

volatile uint64_t g_uChecksum = 0;

template <typename HASH> double Measure ( const std::vector<ProbeKey_t> & dKeys )
{
	const size_t nLoops = std::max<size_t> ( 1, 1000000/dKeys.size() );
	uint64_t uSum = 0;
	const auto tStart = std::chrono::steady_clock::now();
	for ( size_t i=0; i<nLoops; ++i )
		for ( const auto & k : dKeys )
		{
			const auto h = HASH::Hash(k);
			asm volatile ( "" : : "r"(h) : "memory" ); // prevent loop hoisting and bulk vectorization
			uSum += h;
		}
	const auto nElapsed = std::chrono::duration_cast<std::chrono::nanoseconds> ( std::chrono::steady_clock::now()-tStart ).count();
	g_uChecksum = uSum;
	return double(nElapsed)/(nLoops*dKeys.size());
}

template <typename HASH> void Report ( const std::string & sSet, const char * sHash, const std::vector<ProbeKey_t> & dKeys, std::vector<double> dSamples )
{
	std::array<size_t,16> dLow{}, dHigh{};
	std::unordered_set<uint32_t> dUnique;
	for ( const auto & k : dKeys )
	{
		auto h = HASH::Hash(k);
		assert ( h==HASH::Hash(k) );
		++dLow[h&15];
		++dHigh[h>>28];
		dUnique.insert(h);
	}
	auto Used = []( const auto & d ) { return std::count_if ( d.begin(), d.end(), [](size_t n){return n!=0;} ); };
	auto Ratio = [&]( const auto & d ) { return 16.0**std::max_element(d.begin(),d.end())/dKeys.size(); };
	std::sort(dSamples.begin(),dSamples.end());
	std::cout << "{\"dataset\":\"" << sSet << "\",\"hash\":\"" << sHash << "\",\"keys\":" << dKeys.size()
		<< ",\"ns_per_key_median\":" << dSamples[3] << ",\"collisions32\":" << dKeys.size()-dUnique.size()
		<< ",\"low4_shards_used\":" << Used(dLow) << ",\"low4_max_over_mean\":" << Ratio(dLow)
		<< ",\"high4_shards_used\":" << Used(dHigh) << ",\"high4_max_over_mean\":" << Ratio(dHigh) << "}\n";
}

int main ( int argc, char ** argv )
{
	if ( argc!=2 ) return 2;
	assert ( BKDR_t<131>::Hash({0,0})==0 );
	assert ( BKDR_t<131>::Hash({1,0})!=BKDR_t<131>::Hash({0,1}) );
	std::ifstream tInput(argv[1]);
	if ( !tInput ) return 3;
	std::map<std::string,std::vector<ProbeKey_t>> mKeys;
	std::string sSet;
	ProbeKey_t k;
	while ( tInput>>sSet>>k.m_uIndex>>k.m_uOffset ) mKeys[sSet].push_back(k);
	if ( !tInput.eof() || mKeys.empty() ) return 4;
	using Fn = double (*)(const std::vector<ProbeKey_t> &);
	const std::array<Fn,5> dFns { Measure<CRC_t>, Measure<XXH_t>, Measure<BKDR_t<131>>, Measure<BKDR_t<1313>>, Measure<BKDRFold_t> };
	std::cout << std::setprecision(10);
	for ( const auto & tPair : mKeys )
	{
		const auto & dKeys = tPair.second;
		std::array<std::vector<double>,5> dSamples;
		for ( auto fn : dFns ) fn(dKeys);
		for ( int i=0; i<7; ++i )
			for ( int j=0; j<5; ++j )
			{
				int n = (i+j)%5;
				dSamples[n].push_back(dFns[n](dKeys));
			}
		Report<CRC_t> ( tPair.first, "CRC32-chain", dKeys, dSamples[0] );
		Report<XXH_t> ( tPair.first, "XXH3-64-seeded", dKeys, dSamples[1] );
		Report<BKDR_t<131>> ( tPair.first, "BKDR-131", dKeys, dSamples[2] );
		Report<BKDR_t<1313>> ( tPair.first, "BKDR-1313", dKeys, dSamples[3] );
		Report<BKDRFold_t> ( tPair.first, "BKDR-131-xorfold16", dKeys, dSamples[4] );
	}
}
