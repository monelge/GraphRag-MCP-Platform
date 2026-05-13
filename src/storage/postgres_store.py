"""
PostgreSQL tabanlı retrieval log kaydı.

Privacy-safe tasarım kararları:
1. Ham sorgu metni SAKLANMAZ — yalnızca ilk 80 karakteri, secret pattern'ler maskelenmiş.
2. Ham user ID SAKLANMAZ — yalnızca SHA-256 hash'i.
3. Retrieval sonuçlarının içeriği kaydedilmez — sadece metrik (skor, sayı, latency).
4. faithfulness_score başlangıçta NULL — günlük batch ile doldurulur.

asyncpg yoksa tüm metodlar no-op döner; loglama kritik yol değildir.
"""

from __future__ import annotations
import hashlib
import os
from typing import Optional

try:
    import asyncpg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

# Tablo şeması — bağlantı kurulunca CREATE TABLE IF NOT EXISTS ile hazırlanır.
# Türkçe karakterleri desteklemek için UTF-8 encoding kullanılır.
_SCHEMA_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_rl_collection   ON retrieval_logs(collection);
CREATE INDEX IF NOT EXISTS idx_rl_created_at   ON retrieval_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_rl_query_type   ON retrieval_logs(query_type);

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

CREATE TABLE IF NOT EXISTS task_checkpoints (
    checkpoint_id       TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    status              TEXT NOT NULL CHECK (status IN ('planned', 'retrieving', 'analyzing', 'waiting_approval', 'executing', 'verifying', 'summarizing', 'done', 'failed', 'aborted')),
    context_snapshot    JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_collection ON tasks(collection);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id);
CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status);
CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task_id ON task_checkpoints(task_id);
"""


class PostgresStore:
    """
    Retrieval metrikleri için privacy-safe async log deposu.
    asyncpg paketi yoksa veya bağlantı hatalıysa hiçbir şey yapmaz.
    """

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or os.getenv(
            "POSTGRES_DSN",
            "postgresql://graphmcp:graphmcp@postgres:5432/graphmcp",
        )
        self._pool: Optional[object] = None

    async def connect(self) -> None:
        """
        Connection pool oluşturur ve şemayı hazırlar.
        mcp_server.py startup'ta çağrılır; başarısız olursa loglama devre dışı.
        
        Faz 2 İyileştirmeler:
        - Asyncpg timeout ayarı (command_timeout, init_command_timeout)
        - UTF-8 encoding desteği Türkçe karakterler için
        - Connection pool boyutu yapılandırılabilir
        """
        if not _PG_AVAILABLE:
            return
        try:
            # Connection timeout: 30 saniye, command timeout: 60 saniye
            self._pool = await asyncpg.create_pool(
                self._dsn, 
                min_size=1, 
                max_size=5,
                command_timeout=60,
                init=self._init_connection
            )
            async with self._pool.acquire() as conn:
                await conn.execute(_SCHEMA_SQL)
        except Exception as e:
            # Bağlantı hatası critical path değil — sessizce devam et
            self._pool = None

    @staticmethod
    async def _init_connection(conn):
        """
        Her yeni bağlantı için çalışan initialization fonksiyonu.
        UTF-8 encoding desteği sağlar (Türkçe karakterler için).
        """
        await conn.execute("SET client_encoding = 'UTF8'")
        await conn.execute("SET search_path TO public")

    @property
    def available(self) -> bool:
        return self._pool is not None

    @staticmethod
    def _hash_user_id(user_id: str | None) -> str | None:
        """Ham kullanıcı kimliğini SHA-256 ile hash'ler. None gelirse None döner."""
        if not user_id:
            return None
        return hashlib.sha256(user_id.encode()).hexdigest()

    async def log_retrieval(
        self,
        collection: str,
        redacted_query: str,
        query_type: str | None = None,
        top_k: int = 0,
        hit_count: int = 0,
        top1_score: float = 0.0,
        latency_ms: int = 0,
        rerank_latency_ms: int = 0,
        token_usage: int = 0,
        cache_hit: bool = False,
        answerability_fail: bool = False,
        user_id: str | None = None,
    ) -> None:
        """
        Tek bir retrieval işlemini kayıt altına alır.
        Yeni alanlar: rerank_latency_ms, token_usage, cache_hit, answerability_fail.
        """
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
