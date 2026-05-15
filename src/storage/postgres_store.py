"""
PostgreSQL tabanlı retrieval log ve task/checkpoint depolama katmanı.

Neden migration tablosu var?
1. Şema değişikliklerini idempotent şekilde izlemek için.
2. Docker restart sonrası tekrar uygulanabilirlik sağlamak için.
3. Checkpoint/resume fazını güvenli genişletmek için.
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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

-- LLM çağrılarının prompt/completion token maliyetlerini saklar.
-- Neden ayrı tablo? retrieval_logs embedding tokenları içerir; LLM usage farklı granülerlikte.
CREATE TABLE IF NOT EXISTS model_usage_logs (
    id                  BIGSERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model               TEXT NOT NULL,
    task_id             TEXT,          -- hangi agent task'ından geldi (opsiyonel)
    node_name           TEXT,          -- hangi pipeline node'undan geldi (opsiyonel)
    prompt_tokens       INT NOT NULL DEFAULT 0,
    completion_tokens   INT NOT NULL DEFAULT 0,
    total_tokens        INT NOT NULL DEFAULT 0,
    latency_ms          INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mul_model      ON model_usage_logs(model);
CREATE INDEX IF NOT EXISTS idx_mul_created_at ON model_usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_mul_task_id    ON model_usage_logs(task_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type  TEXT NOT NULL,
    collection  TEXT,
    task_id     TEXT,
    actor       TEXT DEFAULT 'agent',
    summary     TEXT,
    metadata    JSONB
);
CREATE INDEX IF NOT EXISTS idx_ae_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ae_task_id ON audit_events(task_id);
CREATE INDEX IF NOT EXISTS idx_ae_created_at ON audit_events(created_at);
"""

_MIGRATIONS = [
    (1, "Initial retrieval/task schema"),
    (2, "Checkpoint and schema migration tables"),
    (3, "LLM model_usage_logs table"),
    (4, "Audit events table"),
]


class PostgresStore:
    """Privacy-safe loglama ve task/checkpoint saklama için PostgreSQL store."""

    def __init__(self, dsn: str = None):
        self._dsn = dsn or config.postgres_dsn
        self._pool: Optional[object] = None

    async def connect(self) -> None:
        if not _PG_AVAILABLE:
            logger.warning(
                "asyncpg paketi yüklenmedi, PostgreSQL desteği devre dışı kalacak. 'asyncpg' gereksinimini kontrol edin."
            )
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
            logger.info("PostgreSQL bağlantısı kuruldu")
        except Exception as exc:
            parsed = urlparse(self._dsn)
            host = parsed.hostname or "unknown"
            port = parsed.port or "unknown"
            db = parsed.path.lstrip("/") or "unknown"
            logger.warning(
                "PostgreSQL bağlantısı kurulamadı: host=%s port=%s db=%s error=%s",
                host,
                port,
                db,
                exc,
            )
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
            logger.debug("PostgreSQL pool yok, retrieval_log atlanıyor")
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
        except Exception as _exc:
            logger.warning("retrieval_log yazılamadı: %s", _exc)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def log_llm_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        task_id: str = None,
        node_name: str = None,
    ) -> None:
        """LLM çağrısının token kullanımını model_usage_logs tablosuna yazar."""
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO model_usage_logs
                        (model, task_id, node_name, prompt_tokens,
                         completion_tokens, total_tokens, latency_ms)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    model,
                    task_id,
                    node_name,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    latency_ms,
                )
        except Exception as _exc:
            logger.debug("DB write hatası: %s", _exc)

    async def log_audit_event(
        self,
        event_type: str,
        collection: str = "",
        task_id: str = "",
        summary: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Audit olaylarını privacy-safe biçimde audit_events tablosuna yazar."""
        if not self._pool:
            logger.debug("PostgreSQL pool yok, audit_event atlanıyor")
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, collection, task_id, summary, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    event_type,
                    collection or None,
                    task_id or None,
                    summary or None,
                    json.dumps(metadata or {}),
                )
        except Exception as exc:
            logger.debug("audit_event yazma hatası: %s", exc)

    async def get_llm_usage_stats(self, days: int = 7) -> list[dict]:
        """Son N günün model bazlı token özetini döndürür."""
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        model,
                        COUNT(*)             AS calls,
                        SUM(prompt_tokens)   AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(total_tokens)    AS total_tokens,
                        AVG(latency_ms)::INT AS avg_latency_ms
                    FROM model_usage_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                    GROUP BY model
                    ORDER BY total_tokens DESC
                    """,
                    str(days),
                )
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def get_retrieval_stats(self, days: int = 7) -> list[dict]:
        """Son N günün collection bazlı retrieval özetini döndürür."""
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        collection,
                        query_type,
                        COUNT(*)                      AS calls,
                        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)         AS cache_hits,
                        SUM(CASE WHEN answerability_fail THEN 1 ELSE 0 END) AS answerability_fails,
                        AVG(latency_ms)::INT          AS avg_latency_ms,
                        AVG(hit_count)::FLOAT         AS avg_hit_count,
                        AVG(top1_score)::FLOAT        AS avg_top1_score
                    FROM retrieval_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                    GROUP BY collection, query_type
                    ORDER BY calls DESC
                    """,
                    str(days),
                )
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def get_audit_stats(self, days: int = 7) -> dict:
        """Son N günün event_type bazlı audit özeti ile en son 5 olayı döndürür."""
        if not self._pool:
            return {"summary": [], "recent": []}
        try:
            async with self._pool.acquire() as conn:
                # Event tipine göre sayım
                summary_rows = await conn.fetch(
                    """
                    SELECT
                        event_type,
                        COUNT(*) AS count,
                        MAX(created_at) AS last_seen
                    FROM audit_events
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                    GROUP BY event_type
                    ORDER BY count DESC
                    """,
                    str(days),
                )
                # En son 5 kayıt (debug için)
                recent_rows = await conn.fetch(
                    """
                    SELECT event_type, collection, task_id, summary, created_at
                    FROM audit_events
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    str(days),
                )
                return {
                    "summary": [dict(r) for r in summary_rows],
                    "recent": [dict(r) for r in recent_rows],
                }
        except Exception:
            return {"summary": [], "recent": []}
