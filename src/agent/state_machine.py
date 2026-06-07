"""
Agent State Machine — versiyonlu PostgreSQL checkpoint + Redis rehydration.

Her TDAD adımı geçişinde checkpoint PostgreSQL'e yazılır.
Redis cache (TTL=1h) hız için kullanılır; boşsa PG'den rehydrate edilir.

Checkpoint versiyonu: şema değişikliklerinde geriye dönük uyumluluk.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

CHECKPOINT_VERSION = 1
SESSION_TTL: int = int(os.getenv("SESSION_CONTEXT_TTL_SECONDS", "3600"))

# Agent görev durum makinesi durumları
TASK_STATUSES = (
    "PENDING", "RUNNING", "COMPLETED", "FAILED", "SUSPENDED", "CANCELLED"
)


@dataclass
class AgentCheckpoint:
    """Bir TDAD görevinin anlık durumunu taşır."""
    version:          int   = CHECKPOINT_VERSION
    task_id:          str   = ""
    step:             str   = "SPEC"       # SPEC|TEST|CONTEXT|EDIT|VERIFY|IMPACT|REFLECT|COMMIT
    current_tier:     str   = "TIER_CHEAP"
    selected_model:   str   = ""
    reflection_count: int   = 0
    opened_files:     list  = field(default_factory=list)
    current_branch:   str   = ""
    last_failures:    list  = field(default_factory=list)
    workspace_path:   str   = ""
    snapshot_ref:     str   = ""
    goal:             str   = ""
    collection:       str   = ""
    project_path:     str   = ""
    tokens_used:      int   = 0
    created_at:       float = field(default_factory=time.time)
    updated_at:       float = field(default_factory=time.time)
    extra:            dict  = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "AgentCheckpoint":
        d = json.loads(data) if isinstance(data, str) else data
        version = d.get("version", 0)
        if version < CHECKPOINT_VERSION:
            d = _migrate_checkpoint(d, version)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _migrate_checkpoint(data: dict, from_version: int) -> dict:
    """Eski checkpoint şemalarını güncel versiyona yükseltir."""
    data["version"] = CHECKPOINT_VERSION
    # v0 → v1: reflection_count yoksa ekle
    data.setdefault("reflection_count", 0)
    data.setdefault("opened_files", [])
    data.setdefault("last_failures", [])
    data.setdefault("workspace_path", "")
    data.setdefault("snapshot_ref", "")
    data.setdefault("tokens_used", 0)
    data.setdefault("extra", {})
    logger.debug("Checkpoint migrated v%d → v%d", from_version, CHECKPOINT_VERSION)
    return data


class AgentStateMachine:
    """
    PostgreSQL checkpoint + Redis cache ile görev durumu yönetir.

    postgres_store: PostgresStore nesnesi VEYA asyncpg Pool nesnesi.
    redis_store:    RedisStore nesnesi (opsiyonel).
    """

    def __init__(self, postgres_store=None, redis_store=None) -> None:
        self._pg_store = postgres_store   # PostgresStore veya asyncpg Pool
        self._redis    = redis_store

    @property
    def _pool(self):
        """asyncpg Pool'u döner; PostgresStore sarmalıysa .pool/_pool alanını alır."""
        if self._pg_store is None:
            return None
        # asyncpg Pool doğrudan verilmişse
        import asyncpg
        if isinstance(self._pg_store, asyncpg.pool.Pool):
            return self._pg_store
        # PostgresStore sarmalı
        return getattr(self._pg_store, "_pool", None)

    async def _pg_execute(self, sql: str, *args) -> None:
        pool = self._pool
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(sql, *args)

    async def _pg_fetch(self, sql: str, *args) -> list:
        pool = self._pool
        if pool is None:
            return []
        async with pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    # ── Kayıt / Yükleme ───────────────────────────────────────────────────

    async def save(self, cp: AgentCheckpoint) -> None:
        """Checkpoint'i hem Redis hem PostgreSQL'e yazar."""
        cp.updated_at = time.time()

        # Redis cache
        await self._redis_set(cp)

        # PostgreSQL kalıcı depolama
        await self._pg_upsert(cp)

    async def load(self, task_id: str) -> Optional[AgentCheckpoint]:
        """Redis'ten yükler; yoksa PostgreSQL'den rehydrate eder."""
        cp = await self._redis_get(task_id)
        if cp:
            return cp

        # PostgreSQL fallback — full rehydration
        cp = await self._pg_get(task_id)
        if cp:
            logger.info("Checkpoint PG'den rehydrate edildi: task=%s", task_id)
            await self._redis_set(cp)   # cache'i doldur
        return cp

    async def create(
        self,
        task_id: str,
        goal: str,
        collection: str,
        project_path: str,
        tier: str = "TIER_CHEAP",
        model: str = "",
    ) -> AgentCheckpoint:
        cp = AgentCheckpoint(
            task_id=task_id,
            goal=goal,
            collection=collection,
            project_path=project_path,
            current_tier=tier,
            selected_model=model,
        )
        await self.save(cp)
        return cp

    async def delete(self, task_id: str) -> None:
        """Redis cache'i temizler (PG kaydı korunur, audit için)."""
        if self._redis:
            try:
                r = await self._redis._get_client()
                await r.delete(self._redis_key(task_id))
            except Exception as exc:
                logger.warning("Redis checkpoint silinemedi (%s): %s", task_id, exc)

    # ── Görev durumu güncelleme ────────────────────────────────────────────

    async def update_task_status(self, task_id: str, status: str) -> None:
        """PostgreSQL tasks tablosundaki durumu günceller."""
        if not self._pool:
            return
        if status not in TASK_STATUSES:
            logger.warning("Geçersiz task status: %s", status)
            return
        try:
            await self._pg_execute(
                "UPDATE agent_tasks SET status=$1, updated_at=NOW() WHERE task_id=$2",
                status, task_id,
            )
        except Exception as exc:
            logger.warning("Task status güncellenemedi (%s → %s): %s", task_id, status, exc)

    async def create_task_record(self, cp: AgentCheckpoint, status: str = "RUNNING") -> None:
        """agent_tasks tablosuna yeni kayıt ekler."""
        if not self._pool:
            return
        try:
            await self._pg_execute(
                """
                INSERT INTO agent_tasks
                    (task_id, goal, collection, project_path, status, tier, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,NOW(),NOW())
                ON CONFLICT (task_id) DO UPDATE
                    SET status=$5, updated_at=NOW()
                """,
                cp.task_id, cp.goal, cp.collection,
                cp.project_path, status, cp.current_tier,
            )
        except Exception as exc:
            logger.warning("agent_tasks kaydı oluşturulamadı: %s", exc)

    async def get_active_task_ids(self) -> set[str]:
        """PostgreSQL'de RUNNING veya SUSPENDED olan task_id'leri döner."""
        if not self._pool:
            return set()
        try:
            rows = await self._pg_fetch(
                "SELECT task_id FROM agent_tasks WHERE status IN ('RUNNING','SUSPENDED')"
            )
            return {r["task_id"] for r in rows}
        except Exception as exc:
            logger.warning("Active task_id'ler alınamadı: %s", exc)
            return set()

    async def get_task_history(self, collection: str, limit: int = 20) -> list[dict]:
        if not self._pool:
            return []
        try:
            rows = await self._pg_fetch(
                """SELECT task_id, goal, status, tier, created_at, updated_at
                   FROM agent_tasks WHERE collection=$1
                   ORDER BY created_at DESC LIMIT $2""",
                collection, limit,
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("Task history alınamadı: %s", exc)
            return []

    # ── Redis yardımcıları ────────────────────────────────────────────────

    @staticmethod
    def _redis_key(task_id: str) -> str:
        return f"agent:checkpoint:{task_id}"

    async def _redis_set(self, cp: AgentCheckpoint) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set_raw(self._redis_key(cp.task_id), cp.to_json(), ttl=SESSION_TTL)
        except Exception as exc:
            logger.debug("Redis checkpoint yazılamadı (%s): %s", cp.task_id, exc)

    async def _redis_get(self, task_id: str) -> Optional[AgentCheckpoint]:
        if not self._redis:
            return None
        try:
            raw = await self._redis.get_raw(self._redis_key(task_id))
            if raw:
                return AgentCheckpoint.from_json(raw)
        except Exception as exc:
            logger.debug("Redis checkpoint okunamadı (%s): %s", task_id, exc)
        return None

    # ── PostgreSQL yardımcıları ───────────────────────────────────────────

    async def _pg_upsert(self, cp: AgentCheckpoint) -> None:
        if not self._pool:
            return
        try:
            await self._pg_execute(
                """
                INSERT INTO agent_checkpoints
                    (task_id, version, step, current_tier, selected_model,
                     reflection_count, opened_files, current_branch,
                     last_failures, workspace_path, snapshot_ref,
                     goal, collection, project_path, tokens_used, extra, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW())
                ON CONFLICT (task_id) DO UPDATE SET
                    version=$2, step=$3, current_tier=$4, selected_model=$5,
                    reflection_count=$6, opened_files=$7, current_branch=$8,
                    last_failures=$9, workspace_path=$10, snapshot_ref=$11,
                    tokens_used=$15, extra=$16, updated_at=NOW()
                """,
                cp.task_id, cp.version, cp.step, cp.current_tier, cp.selected_model,
                cp.reflection_count,
                json.dumps(cp.opened_files), cp.current_branch,
                json.dumps(cp.last_failures), cp.workspace_path, cp.snapshot_ref,
                cp.goal, cp.collection, cp.project_path,
                cp.tokens_used, json.dumps(cp.extra),
            )
        except Exception as exc:
            logger.warning("PG checkpoint yazılamadı (%s): %s", cp.task_id, exc)

    async def _pg_get(self, task_id: str) -> Optional[AgentCheckpoint]:
        if not self._pool:
            return None
        try:
            rows = await self._pg_fetch(
                "SELECT * FROM agent_checkpoints WHERE task_id=$1", task_id
            )
            if not rows:
                return None
            row = dict(rows[0])
            # JSONB alanları parse et
            for key in ("opened_files", "last_failures", "extra"):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
                elif row.get(key) is None:
                    row[key] = [] if key != "extra" else {}
            return AgentCheckpoint.from_json(row)
        except Exception as exc:
            logger.warning("PG checkpoint okunamadı (%s): %s", task_id, exc)
            return None


# ── PostgreSQL migration SQL ──────────────────────────────────────────────────
AGENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    task_id          TEXT PRIMARY KEY,
    version          INT  NOT NULL DEFAULT 1,
    step             TEXT NOT NULL DEFAULT 'SPEC',
    current_tier     TEXT NOT NULL DEFAULT 'TIER_CHEAP',
    selected_model   TEXT NOT NULL DEFAULT '',
    reflection_count INT  NOT NULL DEFAULT 0,
    opened_files     JSONB DEFAULT '[]',
    current_branch   TEXT NOT NULL DEFAULT '',
    last_failures    JSONB DEFAULT '[]',
    workspace_path   TEXT NOT NULL DEFAULT '',
    snapshot_ref     TEXT NOT NULL DEFAULT '',
    goal             TEXT NOT NULL DEFAULT '',
    collection       TEXT NOT NULL DEFAULT '',
    project_path     TEXT NOT NULL DEFAULT '',
    tokens_used      INT  NOT NULL DEFAULT 0,
    extra            JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_cp_task_id ON agent_checkpoints(task_id);

CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id      TEXT PRIMARY KEY,
    goal         TEXT NOT NULL DEFAULT '',
    collection   TEXT NOT NULL DEFAULT '',
    project_path TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','SUSPENDED','CANCELLED')),
    tier         TEXT NOT NULL DEFAULT 'TIER_CHEAP',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status     ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_collection ON agent_tasks(collection);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created    ON agent_tasks(created_at DESC);
"""
