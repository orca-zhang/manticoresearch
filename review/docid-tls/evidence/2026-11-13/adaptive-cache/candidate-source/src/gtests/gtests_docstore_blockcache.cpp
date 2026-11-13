// Copyright (c) 2026, Manticore Software LTD (https://manticoresearch.com)
// Distributed under the GNU General Public License, version 3 or later.

#include <gtest/gtest.h>
#include "docstore.h"
#include "indexsettings.h"
#include "threadutils.h"
#include "std/lrucache.h"

#include <atomic>
#include <string>
#include <thread>
#include <vector>

namespace
{
struct CacheTestData_t
{
	BYTE * m_pData;
	DWORD m_uSize;
};

struct CacheTestUtil_t
{
	static DWORD GetHash ( int iKey ) { return DWORD(iKey)*2654435761U; }
	static bool Equal ( int a, int b ) { return a==b; }
	static DWORD GetSize ( const CacheTestData_t & tData ) { return tData.m_uSize; }
	static void Reset ( CacheTestData_t & tData ) { delete[] tData.m_pData; }
};

class AdaptiveLruTest_c : public LRUCache_T<int, CacheTestData_t, CacheTestUtil_t>
{
	using BASE = LRUCache_T<int, CacheTestData_t, CacheTestUtil_t>;
public:
	explicit AdaptiveLruTest_c ( bool bAdaptive, int64_t iLimit = 512*1024 )
		: BASE ( iLimit, iLimit, bAdaptive ? 16*1024 : 0 ) {}
	int64_t Used() { return GetUsedBytes(); }
	void Put ( int iKey )
	{
		CacheTestData_t tData;
		if ( Find ( iKey, tData ) )
		{
			Release(iKey);
			return;
		}
		tData = { new BYTE[1] { BYTE(iKey%251) }, 1024 };
		if ( Add ( iKey, tData ) )
			Release(iKey);
		else
			CacheTestUtil_t::Reset(tData);
	}
	void Hot ( int iReads = 30000 )
	{
		for ( int i=0; i<iReads; ++i ) Put(i%4);
	}
};

TEST ( AdaptiveLru, LazyGrowthAndHardLimit )
{
	AdaptiveLruTest_c tCache(true);
	ASSERT_EQ ( tCache.Used(), 0 );
	for ( int i=0; i<1000; ++i )
	{
		tCache.Put(i);
		ASSERT_LE ( tCache.Used(), 512*1024 );
	}
	ASSERT_GT ( tCache.Used(), 16*1024 );
}

TEST ( AdaptiveLru, HotSetChangeReclaimsColdBlocks )
{
	AdaptiveLruTest_c tCache(true);
	for ( int i=0; i<256; ++i ) tCache.Put(i);
	ASSERT_GT ( tCache.Used(), 128*1024 );
	tCache.Hot();
	ASSERT_LE ( tCache.Used(), 16*1024 );
	for ( int i=0; i<4; ++i )
	{
		CacheTestData_t tData;
		ASSERT_TRUE ( tCache.Find ( i, tData ) );
		EXPECT_EQ ( *tData.m_pData, i );
		tCache.Release(i);
	}
}

TEST ( AdaptiveLru, ManualModeRetainsExistingBehavior )
{
	AdaptiveLruTest_c tCache(false);
	for ( int i=0; i<256; ++i ) tCache.Put(i);
	const auto iUsed = tCache.Used();
	tCache.Hot();
	ASSERT_EQ ( tCache.Used(), iUsed );
}

TEST ( AdaptiveLru, ReferencedBlocksSurviveReclamation )
{
	AdaptiveLruTest_c tCache(true);
	std::vector<CacheTestData_t> dPinned(256);
	for ( int i=0; i<256; ++i )
	{
		tCache.Put(i);
		ASSERT_TRUE ( tCache.Find ( i, dPinned[i] ) );
	}
	const auto iUsed = tCache.Used();
	tCache.Hot();
	ASSERT_EQ ( tCache.Used(), iUsed );
	for ( int i=0; i<256; ++i )
	{
		EXPECT_EQ ( *dPinned[i].m_pData, i%251 );
		tCache.Release(i);
	}
	tCache.Hot(2048);
	ASSERT_LE ( tCache.Used(), 16*1024 );
}

TEST ( AdaptiveLru, ConcurrentGrowthReadsAndReclamation )
{
	AdaptiveLruTest_c tCache(true, 128*1024);
	std::atomic<int> iFailures { 0 };
	std::vector<std::thread> dThreads;
	for ( int i=0; i<8; ++i )
		dThreads.emplace_back ( [&,i] {
			for ( int j=0; j<30000; ++j )
			{
				int iKey = j<5000 ? (j*31+i*173)%1024 : j%4;
				tCache.Put(iKey);
				CacheTestData_t tData;
				if ( tCache.Find ( iKey, tData ) )
				{
					if ( *tData.m_pData!=iKey%251 ) ++iFailures;
					tCache.Release(iKey);
				}
			}
		} );
	for ( auto & tThread : dThreads ) tThread.join();
	ASSERT_EQ ( iFailures.load(), 0 );
	ASSERT_LE ( tCache.Used(), 16*1024 );
}

class DocstoreBlockCacheTest : public ::testing::TestWithParam<bool>
{
protected:
	void SetUp() override
	{
		InitDocstore ( 2*1024*1024, GetParam() );
		ASSERT_EQ ( GetDocstoreCacheUsedBytes(), 0 );
		const auto * pInfo = testing::UnitTest::GetInstance()->current_test_info();
		std::string sName = pInfo->name();
		for ( auto & c : sName ) if ( c=='/' ) c='_';
		for ( int i=0; i<2; ++i )
			m_dFiles[i].SetSprintf ( "__docstore_blocks_%d_%s_%d.spds", GetOsProcessId(), sName.c_str(), i );
	}

	void TearDown() override
	{
		ShutdownDocstore();
		for ( const auto & sFile : m_dFiles ) unlink(sFile.cstr());
	}

	static std::string Value ( int iVersion, int iRow, int iSize )
	{
		auto sPrefix = std::to_string(iVersion)+":"+std::to_string(iRow)+":";
		return sPrefix+std::string ( iSize-sPrefix.size(), char('a'+iRow%26) );
	}

	void Write ( int iFile, int iVersion, int iRows, int iSize )
	{
		CSphString sError;
		DocstoreSettings_t tSettings;
		tSettings.m_uBlockSize = 16384;
		tSettings.m_eCompression = Compression_e::LZ4;
		auto pBuilder = CreateDocstoreBuilder ( m_dFiles[iFile], tSettings, 65536, sError );
		ASSERT_TRUE(pBuilder) << sError.cstr();
		ASSERT_EQ ( pBuilder->AddField ( "body", DOCSTORE_TEXT ), 0 );
		for ( int i=0; i<iRows; ++i )
		{
			auto sValue = Value ( iVersion, i, iSize );
			DocstoreBuilder_i::Doc_t tDoc;
			tDoc.m_dFields.Add ( { reinterpret_cast<BYTE *>(sValue.data()), int(sValue.size()) } );
			pBuilder->AddDoc ( i, tDoc );
		}
		pBuilder->Finalize();
	}

	std::unique_ptr<Docstore_i> Open ( int iFile, int64_t iIndex )
	{
		CSphString sError;
		auto pStore = CreateDocstore ( iIndex, m_dFiles[iFile], sError );
		EXPECT_TRUE(pStore) << sError.cstr();
		return pStore;
	}

	static bool Matches ( const Docstore_i & tStore, int64_t iSession, int iVersion, int iRow, int iSize )
	{
		auto tDoc = tStore.GetDoc ( iRow, nullptr, iSession, false );
		if ( tDoc.m_dFields.GetLength()!=1 ) return false;
		const auto & dValue = tDoc.m_dFields[0];
		return std::string ( reinterpret_cast<const char *>(dValue.Begin()), dValue.GetLength() )==Value ( iVersion, iRow, iSize );
	}

	CSphString m_dFiles[2];
};

TEST_P ( DocstoreBlockCacheTest, ClearAndSameKeyReplacement )
{
	Write ( 0, 1, 256, 128 );
	Write ( 1, 2, 256, 128 );
	auto pStore = Open ( 0, 801 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	pStore->CreateReader(tSession.GetUID());
	for ( int i=0; i<256; ++i ) ASSERT_TRUE ( Matches ( *pStore, tSession.GetUID(), 1, i, 128 ) );
	ClearDocstoreCache();
	ASSERT_EQ ( GetDocstoreCacheUsedBytes(), 0 );
	ASSERT_TRUE ( Matches ( *pStore, tSession.GetUID(), 1, 123, 128 ) );
	pStore.reset();
	pStore = Open ( 1, 801 );
	ASSERT_TRUE(pStore);
	pStore->CreateReader(tSession.GetUID());
	for ( int i=255; i>=0; --i ) ASSERT_TRUE ( Matches ( *pStore, tSession.GetUID(), 2, i, 128 ) );
}

TEST_P ( DocstoreBlockCacheTest, ConcurrentReadsUnderEvictionPressure )
{
	Write ( 0, 1, 2048, 4096 ); // 8 MiB decoded data exceeds the 2 MiB shared budget.
	auto pStore = Open ( 0, 802 );
	ASSERT_TRUE(pStore);
	std::atomic<int> iFailures { 0 };
	std::vector<std::thread> dThreads;
	for ( int i=0; i<8; ++i )
		dThreads.emplace_back ( [&,i] {
			DocstoreSession_c tSession;
			pStore->CreateReader(tSession.GetUID());
			for ( int j=0; j<2048; ++j )
				if ( !Matches ( *pStore, tSession.GetUID(), 1, (j*509+i*173)%2048, 4096 ) ) ++iFailures;
		} );
	for ( auto & tThread : dThreads ) tThread.join();
	ASSERT_EQ ( iFailures.load(), 0 );
	ASSERT_LE ( GetDocstoreCacheUsedBytes(), 2*1024*1024 );
	ClearDocstoreCache();
}

TEST_P ( DocstoreBlockCacheTest, LargeFieldsAndTinyBudgetFallback )
{
	Write ( 0, 1, 40, 70000 );
	auto pStore = Open ( 0, 803 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	pStore->CreateReader(tSession.GetUID());
	for ( int k=0; k<2; ++k )
		for ( int i=0; i<40; ++i ) ASSERT_TRUE ( Matches ( *pStore, tSession.GetUID(), 1, i, 70000 ) );
	pStore.reset();
	ShutdownDocstore();
	InitDocstore ( 1, GetParam() );
	pStore = Open ( 0, 803 );
	ASSERT_TRUE(pStore);
	pStore->CreateReader(tSession.GetUID());
	for ( int i=0; i<40; ++i ) ASSERT_TRUE ( Matches ( *pStore, tSession.GetUID(), 1, i, 70000 ) );
	ASSERT_EQ ( GetDocstoreCacheUsedBytes(), 0 );
}

INSTANTIATE_TEST_SUITE_P ( Modes, DocstoreBlockCacheTest, ::testing::Values ( false, true ) );
}
