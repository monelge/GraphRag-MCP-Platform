"""
PostgreSQL tabanlı retrieval log ve task/checkpoint depolama katmanı.

Neden migration tablosu var?
1. Şema değişikliklerini idempotent şekilde izlemek için.
2. Docker restart sonrası tekrar uygulanabilirlik sağlamak için.
3. Checkpoint/resume fazını güvenli genişletmek için.
"""

from __future__ import annotations

from typing import Optional

from src.shared.config import config
from src.shared.utils import sha256_hash

try:
    import asyncpg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_logs (
    id                  BIGSERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collection          TEXT NOT NULL,
    query_type          TEXT,
    redacted_query      TEXT,
    top_k               INT,
    hit_count           INT,
    top1_score          FLOAT,
    latency_ms          INT,
    faithfulness_score  FLOAT,
    rerank_latency_ms   INT,
    token_usage         INT,
    cache_hit           BOOLEAN DEFAULT FALSE,
    answerability_fail  BOOLEAN DEFAULT FALSE,
    user_id_hash        TEXT
);
CREATE INDEX IF NOT EXISTS idx_rl_collection ON retrieval_logs(collection);
CREATE INDEX IF NOT EXISTS idx_rl_created_at ON retrieval_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_rl_query_type ON retrieval_logs(query_type);

CREATE TABLE IF NOT EXISTS tasks (
    task_id             TEXT PRIMARY KEY,
    title               TEXT,
    description         TEXT,
    status              TEXT NOT NULL CHECK (status IN ('planned', 'retrieving', 'analyzing', 'waiting_approval', 'executing', 'verifying', 'summarizing', 'done', 'failed', 'aborted')),
    collection          TEXT,
    context             JSONB DEFAULT '{}',
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_collection ON tasks(collection);

CREATE TABLE IF NOT EXISTS task_steps (
    step_id             TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    description         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'retrieving', 'analyzing', 'waiting_approval', 'executing', 'verifying', 'summarizing', 'done', 'failed', 'aborted')),
    result              TEXT,
    started_at          DOUBLE PRECISION,
    completed_at        DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id);
CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status);

CREATE TABLE IF NOT EXISTS task_checkpoints (
    checkpoint_id   TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    current_node    TEXT NOT NULL,
    step_index      INT NOT NULL DEFAULT 0,
    task_context    JSONB DEFAULT '{}',
    file_patches    JSONB DEFAULT '[]',
    command_results JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task_id ON task_checkpoints(task_id);
CREATE INDEX IF NOT EXISTS idx_task_checkpoints_created ON task_checkpoints(created_at DESC);
"""

_MIGRATIONS = [
    (1, "Initial retrieval/task schema"),
    (2, "Checkpoint and schema migration tables"),
]


class PostgresStore:
    """Privacy-safe loglama ve task/checkpoint saklama için PostgreSQL store."""

    def __init__(self, dsn: str = None):
        self._dsn = dsn or config.postgres_dsn
        self._pool: Optional[object] = None

    async def connect(self) -> None:
        if not _PG_AVAILABLE:
            return
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=1,
                max_size=5,
                command_timeout=60,
                init=self._init_connection,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(_SCHEMA_SQL)
                await self._apply_migrations(conn)
        except Exception:
            self._pool = None

    async def _apply_migrations(self, conn) -> None:
        for version, description in _MIGRATIONS:
            exists = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = $1",
                version,
            )
            if exists:
                continue
            await conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES ($1, $2) ON CONFLICT (version) DO NOTHING",
                version,
                description,
            )

    @staticmethod
    async def _init_connection(conn):
        await conn.execute("SET client_encoding = 'UTF8'")
        await conn.execute("SET search_path TO public")

    @property
    def available(self) -> bool:
        return self._pool is not None

    @staticmethod
    def _hash_user_id(user_id: str = None) -> str:
        return sha256_hash(user_id) if user_id else None

    async def log_retrieval(
        self,
        collection: str,
        redacted_query: str,
        query_type: str = None,
        top_k: int = 0,
        hit_count: int = 0,
        top1_score: float = 0.0,
        latency_ms: int = 0,
        rerank_latency_ms: int = 0,
        token_usage: int = 0,
        cache_hit: bool = False,
        answerability_fail: bool = False,
        user_id: str = None,
    ) -> None:
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO retrieval_logs
                        (collection, redacted_query, query_type, top_k,
                         hit_count, top1_score, latency_ms,
                         rerank_latency_ms, token_usage, cache_hit,
                         answerability_fail, user_id_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    collection,
                    (redacted_query or "")[:80],
                    query_type,
                    top_k,
                    hit_count,
                    top1_score,
                    latency_ms,
                    rerank_latency_ms,
                    token_usage,
                    cache_hit,
                    answerability_fail,
                    self._hash_user_id(user_id),
                )
        except Exception:
            pass

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
