"""
PatchMemoryStore birim testleri.

Mock EpisodicStore + Mock PG pool — offline çalışır.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.patch_memory import (
    PatchMemoryStore,
    PatchRecord,
    _format_content,
    get_patch_memory_store,
    reset_patch_memory_store,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    reset_patch_memory_store()
    yield
    reset_patch_memory_store()


@pytest.fixture
def record() -> PatchRecord:
    return PatchRecord(
        task_id="task-sprint3",
        goal="Fix null pointer in user_service",
        task_type="bugfix",
        language="python",
        patch_content="--- a/user_service.py\n+++ b/user_service.py\n@@ -10 +10 @@\n-return user.name\n+return user.name or 'unknown'",
        affected_files=["src/user_service.py"],
        affected_symbols=["get_username"],
        acceptance_criteria=["test_get_username passes"],
        tier="TIER_CHEAP",
        reflection_count=1,
        commit_hash="abc12345",
        verify_output="1 passed in 0.12s",
        collection="warelogisticcbys",
    )


@pytest.fixture
def mock_episodic():
    ep = AsyncMock()
    ep.store_memory = AsyncMock(return_value="✅ stored")
    ep.search_memory = AsyncMock(return_value=[])
    return ep


@pytest.fixture
def mock_pg_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=conn)

    pg = MagicMock()
    pg._pool = pool
    pg._conn = conn
    return pg


@pytest.fixture
def store(mock_episodic, mock_pg_pool) -> PatchMemoryStore:
    return PatchMemoryStore(episodic_store=mock_episodic, pg_store=mock_pg_pool)


# ── store_patch testleri ──────────────────────────────────────────────────────

class TestStorePatch:
    @pytest.mark.asyncio
    async def test_store_patch_calls_episodic_store(self, store, record, mock_episodic):
        entry_id = await store.store_patch(record)
        mock_episodic.store_memory.assert_called_once()
        assert entry_id  # boş olmamalı

    @pytest.mark.asyncio
    async def test_store_patch_calls_pg_insert(self, store, record, mock_pg_pool):
        await store.store_patch(record)
        mock_pg_pool._conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_store_empty_patch_skipped(self, store, record, mock_episodic):
        record.patch_content = ""
        entry_id = await store.store_patch(record)
        assert entry_id == ""
        mock_episodic.store_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_whitespace_patch_skipped(self, store, record, mock_episodic):
        record.patch_content = "   \n  "
        entry_id = await store.store_patch(record)
        assert entry_id == ""

    @pytest.mark.asyncio
    async def test_patch_hash_dedup_in_pg(self, store, record, mock_pg_pool):
        # Aynı patch iki kez kaydedilirse PG ON CONFLICT DO NOTHING ile deduplicate edilmeli
        await store.store_patch(record)
        await store.store_patch(record)
        assert mock_pg_pool._conn.execute.call_count == 2  # her çağrıda execute çalışır, PG handle eder


# ── recall_similar testleri ───────────────────────────────────────────────────

class TestRecallSimilar:
    @pytest.mark.asyncio
    async def test_recall_returns_empty_when_no_matches(self, store, mock_episodic):
        mock_episodic.search_memory = AsyncMock(return_value=[])
        results = await store.recall_similar("fix bug", "bugfix", "python", "testcol")
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_calls_episodic_with_code_patch_type(self, store, mock_episodic):
        await store.recall_similar("fix null", "bugfix", "python", "testcol", limit=3)
        mock_episodic.search_memory.assert_called_once()
        call_kwargs = mock_episodic.search_memory.call_args[1]
        assert call_kwargs.get("memory_type") == "code_patch"

    @pytest.mark.asyncio
    async def test_recall_returns_records_from_results(self, store, mock_episodic):
        mock_episodic.search_memory = AsyncMock(return_value=[
            {
                "payload": {
                    "task_id": "t1",
                    "name": "Fix null check",
                    "chunk_type": "bugfix",
                    "language": "python",
                    "code": "--- a/foo.py\n+++ b/foo.py",
                    "collection": "testcol",
                    "commit_sha": "abc",
                    "provenance": "agent-TIER_CHEAP",
                }
            }
        ])
        results = await store.recall_similar("fix null", "bugfix", "python", "testcol")
        assert len(results) == 1
        assert results[0].task_type == "bugfix"

    @pytest.mark.asyncio
    async def test_recall_without_episodic_returns_empty(self):
        store = PatchMemoryStore(episodic_store=None, pg_store=None)
        results = await store.recall_similar("anything")
        assert results == []


# ── format_content testi ──────────────────────────────────────────────────────

class TestFormatContent:
    def test_format_truncates_long_patch(self, record):
        record.patch_content = "x" * 5000
        content = _format_content(record)
        # 4000 char limit
        assert "x" * 4001 not in content

    def test_format_includes_goal(self, record):
        content = _format_content(record)
        assert record.goal in content

    def test_format_includes_tier(self, record):
        content = _format_content(record)
        assert record.tier in content


# ── PatchRecord patch_hash testi ─────────────────────────────────────────────

class TestPatchRecord:
    def test_same_content_same_hash(self):
        r1 = PatchRecord(task_id="t1", goal="g", task_type="bugfix", language="python",
                         patch_content="diff content", collection="c")
        r2 = PatchRecord(task_id="t2", goal="g2", task_type="feature", language="go",
                         patch_content="diff content", collection="c")
        assert r1.patch_hash == r2.patch_hash

    def test_different_content_different_hash(self):
        r1 = PatchRecord(task_id="t1", goal="g", task_type="bugfix", language="python",
                         patch_content="diff A", collection="c")
        r2 = PatchRecord(task_id="t2", goal="g", task_type="bugfix", language="python",
                         patch_content="diff B", collection="c")
        assert r1.patch_hash != r2.patch_hash


# ── get_patch_memory_store singleton ─────────────────────────────────────────

class TestSingleton:
    def test_returns_same_instance(self):
        s1 = get_patch_memory_store()
        s2 = get_patch_memory_store()
        assert s1 is s2

    def test_reset_creates_new_instance(self):
        s1 = get_patch_memory_store()
        reset_patch_memory_store()
        s2 = get_patch_memory_store()
        assert s1 is not s2
