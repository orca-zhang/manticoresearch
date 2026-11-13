// Copyright (c) 2026, Manticore Software LTD (https://manticoresearch.com)
// Distributed under the GNU General Public License, version 3 or later.

#include <gtest/gtest.h>
#include "docstore.h"
#include "indexsettings.h"
#include "threadutils.h"

#include <atomic>
#include <future>
#include <string>
#include <thread>
#include <vector>

namespace
{
class DocstoreReadersTest : public ::testing::Test
{
protected:
	void SetUp() override
	{
		InitDocstore(0); // exercise reader lookup rather than the block cache
		const auto * pInfo = testing::UnitTest::GetInstance()->current_test_info();
		for ( int i=0; i<2; ++i )
			m_dFiles[i].SetSprintf ( "__docstore_readers_%d_%s_%d.spds", GetOsProcessId(), pInfo->name(), i );
		Write ( 0, "first" );
		Write ( 1, "second" );
	}

	void TearDown() override
	{
		ShutdownDocstore();
		for ( const auto & sFile : m_dFiles ) unlink(sFile.cstr());
	}

	static std::string Value ( const char * sPrefix, int iRow )
	{
		return std::string(sPrefix)+":"+std::to_string(iRow)+std::string(256,char('a'+iRow));
	}

	void Write ( int iFile, const char * sPrefix )
	{
		CSphString sError;
		DocstoreSettings_t tSettings;
		tSettings.m_uBlockSize = 1024;
		tSettings.m_eCompression = Compression_e::NONE;
		auto pBuilder = CreateDocstoreBuilder ( m_dFiles[iFile], tSettings, 65536, sError );
		ASSERT_TRUE(pBuilder) << sError.cstr();
		ASSERT_EQ ( pBuilder->AddField ( "body", DOCSTORE_TEXT ), 0 );
		for ( int i=0; i<16; ++i )
		{
			auto sValue = Value ( sPrefix, i );
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

	static void Check ( const Docstore_i & tStore, int64_t iSession, const char * sPrefix, int iRow )
	{
		auto tDoc = tStore.GetDoc ( iRow, nullptr, iSession, false );
		ASSERT_EQ ( tDoc.m_dFields.GetLength(), 1 );
		const auto & dValue = tDoc.m_dFields[0];
		EXPECT_EQ ( std::string ( reinterpret_cast<const char *>(dValue.Begin()), dValue.GetLength() ), Value(sPrefix,iRow) );
	}

	CSphString m_dFiles[2];
};

TEST_F ( DocstoreReadersTest, LateCreationAndSameKeyIndexReplacement )
{
	auto pStore = Open ( 0, 101 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	const auto iSession = tSession.GetUID();
	Check ( *pStore, iSession, "first", 0 ); // negative lookup before creation
	pStore->CreateReader(iSession);
	Check ( *pStore, iSession, "first", 1 );
	Check ( *pStore, iSession, "first", 9 ); // repeated positive lookup
	pStore.reset(); // retire the reader with a cached key
	pStore = Open ( 1, 101 ); // deliberately reuse that key with different data
	ASSERT_TRUE(pStore);
	Check ( *pStore, iSession, "second", 2 );
	pStore->CreateReader(iSession);
	Check ( *pStore, iSession, "second", 10 );
}

TEST_F ( DocstoreReadersTest, SessionCleanupAndRegistryRestart )
{
	auto pStore = Open ( 0, 102 );
	ASSERT_TRUE(pStore);
	int64_t iSession;
	{
		DocstoreSession_c tSession;
		iSession = tSession.GetUID();
		pStore->CreateReader(iSession);
		Check ( *pStore, iSession, "first", 3 );
	}
	Check ( *pStore, iSession, "first", 4 ); // retired session uses the pread fallback
	pStore->CreateReader(iSession);
	Check ( *pStore, iSession, "first", 5 );
	ShutdownDocstore();
	InitDocstore(0);
	Check ( *pStore, iSession, "first", 6 ); // old TLS must not survive registry reuse
	pStore->CreateReader(iSession);
	Check ( *pStore, iSession, "first", 7 );
}

TEST_F ( DocstoreReadersTest, IndexReplacementInvalidatesOtherThread )
{
	auto pStore = Open ( 0, 106 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	pStore->CreateReader(tSession.GetUID());
	std::promise<void> tWarmed, tReplaced;
	auto tWarmedFuture = tWarmed.get_future();
	auto tReplacedFuture = tReplaced.get_future();
	std::thread tReader ( [&] {
		Check ( *pStore, tSession.GetUID(), "first", 0 );
		tWarmed.set_value();
		tReplacedFuture.wait();
		if ( pStore )
		{
			Check ( *pStore, tSession.GetUID(), "second", 1 );
			pStore->CreateReader(tSession.GetUID());
			Check ( *pStore, tSession.GetUID(), "second", 2 );
		}
	} );
	tWarmedFuture.wait();
	pStore.reset(); // invalidate the borrowed pointer on another OS thread
	pStore = Open ( 1, 106 );
	tReplaced.set_value();
	tReader.join();
}

TEST_F ( DocstoreReadersTest, ConcurrentSessionsAndCleanup )
{
	auto pFirst = Open ( 0, 103 );
	auto pSecond = Open ( 1, 104 );
	ASSERT_TRUE(pFirst);
	ASSERT_TRUE(pSecond);
	std::vector<std::thread> dThreads;
	for ( int i=0; i<8; ++i )
		dThreads.emplace_back ( [&,i] {
			for ( int j=0; j<40; ++j )
			{
				DocstoreSession_c tSession;
				pFirst->CreateReader(tSession.GetUID());
				pSecond->CreateReader(tSession.GetUID());
				for ( int k=0; k<32; ++k )
				{
					bool bSecond = (k/8+j+i)%2;
					Check ( bSecond ? *pSecond : *pFirst, tSession.GetUID(), bSecond ? "second" : "first", (k+i)%16 );
				}
			}
		} );
	for ( auto & tThread : dThreads ) tThread.join();
}

TEST_F ( DocstoreReadersTest, SessionMovesBetweenOsThreads )
{
	auto pStore = Open ( 0, 105 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	pStore->CreateReader(tSession.GetUID());
	for ( int i=0; i<4; ++i )
	{
		std::thread tThread ( [&,i] {
			for ( int j=0; j<16; ++j ) Check ( *pStore, tSession.GetUID(), "first", (j+i)%16 );
		} );
		tThread.join(); // sequential reader use, as required by the existing API
	}
}

TEST_F ( DocstoreReadersTest, StableReaderDuringConcurrentUnrelatedSessionChurn )
{
	auto pStable = Open ( 0, 107 );
	auto pChurn = Open ( 1, 108 );
	ASSERT_TRUE(pStable);
	ASSERT_TRUE(pChurn);
	DocstoreSession_c tStable;
	pStable->CreateReader(tStable.GetUID());
	Check ( *pStable, tStable.GetUID(), "first", 0 );
	std::promise<void> tStart;
	auto tGo = tStart.get_future().share();
	std::atomic<int> iActive { 4 };
	std::vector<std::thread> dThreads;
	for ( int i=0; i<4; ++i )
		dThreads.emplace_back ( [&,i] {
			tGo.wait();
			for ( int j=0; j<512; ++j )
			{
				DocstoreSession_c tSession;
				pChurn->CreateReader(tSession.GetUID());
				Check ( *pChurn, tSession.GetUID(), "second", (j+i)%16 );
			}
			iActive.fetch_sub(1);
		} );
	tStart.set_value();
	int iReads = 0;
	do
	{
		Check ( *pStable, tStable.GetUID(), "first", iReads%16 );
		++iReads;
	} while ( iActive.load()>0 || iReads<2048 );
	for ( auto & tThread : dThreads ) tThread.join();
}

TEST_F ( DocstoreReadersTest, BudgetRefusalThenReaderCreation )
{
	auto pStore = Open ( 0, 109 );
	ASSERT_TRUE(pStore);
	std::vector<std::unique_ptr<DocstoreSession_c>> dSessions;
	// 300 minimum-size readers exceed the unchanged 8 MiB registry budget.
	for ( int i=0; i<300; ++i )
	{
		dSessions.emplace_back ( new DocstoreSession_c );
		pStore->CreateReader(dSessions.back()->GetUID());
	}
	const auto iLast = dSessions.back()->GetUID();
	Check ( *pStore, iLast, "first", 1 ); // budget refusal uses pread
	dSessions.erase ( dSessions.begin(), dSessions.end()-1 );
	pStore->CreateReader(iLast); // available budget must invalidate cached null
	Check ( *pStore, iLast, "first", 9 );
	Check ( *pStore, iLast, "first", 2 );
}

TEST_F ( DocstoreReadersTest, NegativeLookupThenCreationOnAnotherThread )
{
	auto pStore = Open ( 0, 110 );
	ASSERT_TRUE(pStore);
	DocstoreSession_c tSession;
	Check ( *pStore, tSession.GetUID(), "first", 3 );
	std::thread tCreator ( [&] { pStore->CreateReader(tSession.GetUID()); } );
	tCreator.join();
	Check ( *pStore, tSession.GetUID(), "first", 12 );
}
}
