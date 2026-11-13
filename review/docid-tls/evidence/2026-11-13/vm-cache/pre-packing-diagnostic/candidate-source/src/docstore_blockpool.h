// Copyright (c) 2026, Manticore Software LTD (https://manticoresearch.com)
// Distributed under the GNU General Public License, version 3 or later.

#pragma once

#include "std/mm.h"
#include "std/mutex.h"
#include "std/scopedlock.h"
#include "std/sys.h"
#include "std/vector.h"

#include <cstdlib>

// One pool per cache shard; cached payloads bypass the process heap.
class DocstoreBlockPool_c
{
public:
	explicit DocstoreBlockPool_c ( int64_t iSpareLimit = 64*1024 ) : m_iSpareLimit(iSpareLimit) {}
	~DocstoreBlockPool_c()
	{
		for ( const auto & tBlock : m_dFree ) Unmap ( tBlock.m_pData, tBlock.m_uSize );
		assert ( !m_iMappedBytes );
	}

	static uint64_t AllocationSize ( DWORD uSize )
	{
		const uint64_t uPage = GetMemPageSize();
		return (uint64_t(uSize)+uPage-1)/uPage*uPage;
	}

	BYTE * Allocate ( DWORD uSize )
	{
		const auto uMappedSize = AllocationSize(uSize);
		if ( !uMappedSize || uMappedSize>UINT32_MAX ) return nullptr;
		ScopedMutex_t tLock(m_tLock);
		for ( int i=0; i<m_dFree.GetLength(); ++i )
			if ( m_dFree[i].m_uSize==uMappedSize )
			{
				auto * pData = m_dFree[i].m_pData;
				m_dFree.RemoveFast(i);
				m_iSpareBytes -= uMappedSize;
				return pData;
			}
#if _WIN32
		auto * pData = (BYTE *)VirtualAlloc ( nullptr, uMappedSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE );
		if ( !pData ) return nullptr;
#else
		auto * pData = (BYTE *)mmalloc(uMappedSize);
		if ( !mmapvalid(pData) ) return nullptr;
#endif
		m_iMappedBytes += uMappedSize;
		return pData;
	}

	void Free ( BYTE * pData, DWORD uSize )
	{
		const auto uMappedSize = AllocationSize(uSize);
		ScopedMutex_t tLock(m_tLock);
		// Reuse a few evicted blocks without retaining an old working set.
		if ( m_iSpareBytes+uMappedSize<=uint64_t(m_iSpareLimit) )
		{
			m_dFree.Add ( { pData, DWORD(uMappedSize) } );
			m_iSpareBytes += uMappedSize;
		}
		else
			Unmap ( pData, DWORD(uMappedSize) );
	}

	void GetStats ( int64_t & iMapped, int64_t & iSpare )
	{
		ScopedMutex_t tLock(m_tLock);
		iMapped += m_iMappedBytes;
		iSpare += m_iSpareBytes;
	}

private:
	struct FreeBlock_t { BYTE * m_pData; DWORD m_uSize; };
	CSphMutex m_tLock;
	CSphVector<FreeBlock_t> m_dFree;
	int64_t m_iSpareLimit;
	int64_t m_iMappedBytes = 0;
	int64_t m_iSpareBytes = 0;

	void Unmap ( BYTE * pData, DWORD uSize )
	{
#if _WIN32
		const bool bFreed = !!VirtualFree ( pData, 0, MEM_RELEASE );
#else
		const bool bFreed = mmfree ( pData, uSize )==0;
#endif
		if ( !bFreed ) std::abort();
		m_iMappedBytes -= uSize;
	}
};
