"""
AgentStateMachine birim testleri.

Mock PG + Redis ile Redis→PG fallback, checkpoint versiyonu, save/load/delete.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.state_machine import (
    AgentCheckpoint,
    AgentStateMachine,
    CHECKPOINT_VERSION,
    _migrate_checkpoint,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _FakePool:
    """asyncpg.pool.Pool'u taklit eden fake pool — import gerekmez."""
    def __init__(self):
        self._conn = AsyncMock()
        self._conn.__aenter__ = AsyncMock(return_value=self._conn)
        self._conn.__aexit__ = AsyncMock(return_value=False)
        self._conn.execute = AsyncMock(return_value=None)
        self._conn.fetchrow = AsyncMock(return_value=None)
        self._conn.fetch = AsyncMock(return_value=[])

    def acquire(self):
        return self._conn


@pytest.fixture
def pg():
    """Pool mock — asyncpg import yapmadan."""
    pool = _FakePool()
    store = MagicMock()
    store._pool = pool
    store._conn = pool._conn
    return store


@pytest.fixture
def redis():
    """RedisStore mock — in-memory dict tabanlı."""
    _store: dict[str, str] = {}
    r = AsyncMock()

    async def set_raw(key, value, ttl=None):
        _store[key] = value

    async def get_raw(key):
        return _store.get(key)

    async def delete(key):
        _store.pop(key, None)

    r.set_raw = AsyncMock(side_effect=set_raw)
    r.get_raw = AsyncMock(side_effect=get_raw)
    r.delete = AsyncMock(side_effect=delete)
    r._store = _store
    return r


@pytest.fixture
def sm(pg, redis):
    machine = AgentStateMachine(postgres_store=pg, redis_store=redis)
    # asyncpg import olmadan _pool property'sini override et
    type(machine)._pool = property(lambda self: self._pg_store._pool)
    return machine


@pytest.fixture
def cp() -> AgentCheckpoint:
    return AgentCheckpoint(
        task_id="task-001",
        goal="Fix auth bug",
        collection="warelogisticcbys",
        project_path="/tmp/project",
        current_tier="TIER_CHEAP",
        selected_model="google/gemini-2.5-flash",
    )


# ── AgentCheckpoint serializasyon ────────────────────────────────────────────

class TestCheckpointSerialization:
    def test_to_json_roundtrip(self, cp):
        s = cp.to_json()
        cp2 = AgentCheckpoint.from_json(s)
        assert cp2.task_id == cp.task_id
        assert cp2.goal == cp.goal
        assert cp2.version == CHECKPOINT_VERSION

    def test_from_dict(self, cp):
        d = json.loads(cp.to_json())
        cp2 = AgentCheckpoint.from_json(d)
        assert cp2.task_id == cp.task_id

    def test_version_default(self, cp):
        assert cp.version == CHECKPOINT_VERSION


# ── Checkpoint migration ──────────────────────────────────────────────────────

class TestCheckpointMigration:
    def test_v0_migrates_to_v1(self):
        data = {
            "version": 0,
            "task_id": "t1",
            "step": "SPEC",
            "current_tier": "TIER_CHEAP",
            "selected_model": "",
            "goal": "test",
            "collection": "c",
            "project_path": "/p",
            "current_branch": "",
            "created_at": time.time(),
            "updated_at": time.time(),
            "tokens_used": 0,
        }
        migrated = _migrate_checkpoint(data, 0)
        assert migrated["version"] == CHECKPOINT_VERSION
        assert "reflection_count" in migrated
        assert "extra" in migrated

    def test_from_json_migrates_old_version(self):
        old_data = {
            "version": 0,
            "task_id": "old-task",
            "step": "CONTEXT",
            "current_tier": "TIER_LOCAL",
            "selected_model": "",
            "goal": "old goal",
            "collection": "c",
            "project_path": "/p",
            "current_branch": "",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        cp = AgentCheckpoint.from_json(old_data)
        assert cp.version == CHECKPOINT_VERSION
        assert cp.reflection_count == 0


# ── save / load (Redis hit) ───────────────────────────────────────────────────

class TestSaveLoad:
    @pytest.mark.asyncio
    async def test_save_writes_to_redis(self, sm, cp, redis):
        await sm.save(cp)
        redis.set_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_redis_hit_returns_checkpoint(self, sm, cp, redis):
        await sm.save(cp)
        loaded = await sm.load(cp.task_id)
        assert loaded is not None
        assert loaded.task_id == cp.task_id

    @pytest.mark.asyncio
    async def test_load_redis_miss_falls_back_to_pg(self, sm, cp, pg):
        # Redis boş → PG'ye düşmeli (_pg_fetch → conn.fetch)
        loaded = await sm.load(cp.task_id)
        # PG döndü (boş liste → None)
        pg._conn.fetch.assert_called()

    @pytest.mark.asyncio
    async def test_load_miss_both_returns_none(self, sm):
        result = await sm.load("nonexistent-task")
        assert result is None


# ── create ────────────────────────────────────────────────────────────────────

class TestCreate:
    @pytest.mark.asyncio
    async def test_create_returns_checkpoint(self, sm):
        cp = await sm.create(
            task_id="new-task",
            goal="Add feature",
            collection="testcol",
            project_path="/p",
        )
        assert cp.task_id == "new-task"
        assert cp.step == "SPEC"
        assert cp.version == CHECKPOINT_VERSION
