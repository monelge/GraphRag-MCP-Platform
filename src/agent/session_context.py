"""
Session Context — Redis TTL cache + PostgreSQL fallback ile görev oturum bağlamı.

Her TDAD adımı için derlenmiş bağlam (kod parçaları, bellek, hata geçmişi)
Redis'te SESSION_TTL süreyle tutulur. Redis boşsa PG checkpoint'ten rehydrate edilir.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SESSION_TTL: int = int(os.getenv("SESSION_CONTEXT_TTL_SECONDS", "3600"))
MAX_CODE_CHUNKS: int = int(os.getenv("SESSION_MAX_CODE_CHUNKS", "20"))
MAX_MEMORY_ITEMS: int = int(os.getenv("SESSION_MAX_MEMORY_ITEMS", "10"))


@dataclass
class CodeChunk:
    file_path: str
    content:   str
    relevance: float = 1.0
    source:    str   = "search_code"  # search_code | grep | context_assembler


@dataclass
class SessionContext:
    """Tek TDAD görevi boyunca taşınan çalışma bağlamı."""
    task_id:          str
    goal:             str
    collection:       str
    project_path:     str
    current_step:     str = "SPEC"
    tier:             str = "TIER_CHEAP"

    # GraphRAG'dan gelen kod bağlamı
    code_chunks:      list[dict] = field(default_factory=list)
    memory_items:     list[dict] = field(default_factory=list)

    # Çalışma zamanı durumu
    spec:             str  = ""
    test_code:        str  = ""
    edit_patch:       str  = ""
    verify_output:    str  = ""
    impact_summary:   str  = ""
    reflection_notes: str  = ""
    commit_hash:      str  = ""

    # Meta
    tokens_used:      int   = 0
    created_at:       float = field(default_factory=time.time)
    updated_at:       float = field(default_factory=time.time)

    def add_code_chunk(self, chunk: CodeChunk) -> None:
        """Kod parçası ekler; limit aşılınca en düşük relevance'ı siler."""
        self.code_chunks.append(asdict(chunk))
        if len(self.code_chunks) > MAX_CODE_CHUNKS:
            self.code_chunks.sort(key=lambda c: c.get("relevance", 0), reverse=True)
            self.code_chunks = self.code_chunks[:MAX_CODE_CHUNKS]

    def add_memory_item(self, item: dict) -> None:
        self.memory_items.append(item)
        if len(self.memory_items) > MAX_MEMORY_ITEMS:
            self.memory_items = self.memory_items[-MAX_MEMORY_ITEMS:]

    def build_context_text(self, token_budget: int = 8000) -> str:
        """LLM promptu için düz metin bağlam döner; token bütçesiyle sınırlanır."""
        parts: list[str] = []
        char_budget = token_budget * 4  # ~4 char/token yaklaşımı

        # Bellek öğeleri
        if self.memory_items:
            mem_block = "\n".join(
                f"- {m.get('title', '')}: {m.get('content', '')}"
                for m in self.memory_items[:5]
            )
            parts.append(f"## Bellek\n{mem_block}")

        # Kod parçaları
        for chunk in self.code_chunks:
            file_path = chunk.get("file_path", "?")
            content   = chunk.get("content", "")
            parts.append(f"### {file_path}\n```\n{content}\n```")

        raw = "\n\n".join(parts)
        if len(raw) > char_budget:
            raw = raw[:char_budget] + "\n...[bağlam token bütçesi aşıldı, kırpıldı]"
        return raw

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str | dict) -> "SessionContext":
        d = json.loads(data) if isinstance(data, str) else data
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SessionContextStore:
    """
    Redis TTL cache önde, PostgreSQL checkpoint fallback arkada.

    Redis boşsa AgentCheckpoint'teki `extra` alanına yazılmış
    minimal bağlam JSON'u rehydrate eder.
    """

    def __init__(self, redis_store=None, postgres_store=None) -> None:
        self._redis    = redis_store
        self._pg_store = postgres_store

    @property
    def _pool(self):
        if self._pg_store is None:
            return None
        try:
            import asyncpg
            if isinstance(self._pg_store, asyncpg.pool.Pool):
                return self._pg_store
        except ImportError:
            pass
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

    async def save(self, ctx: SessionContext) -> None:
        ctx.updated_at = time.time()
        await self._redis_set(ctx)
        await self._pg_save_extra(ctx)

    async def load(self, task_id: str) -> Optional[SessionContext]:
        ctx = await self._redis_get(task_id)
        if ctx:
            return ctx

        ctx = await self._pg_load_extra(task_id)
        if ctx:
            logger.info("SessionContext PG'den rehydrate edildi: task=%s", task_id)
            await self._redis_set(ctx)
        return ctx

    async def delete(self, task_id: str) -> None:
        if self._redis:
            try:
                r = await self._redis._get_client()
                await r.delete(self._redis_key(task_id))
            except Exception as exc:
                logger.debug("Session Redis silinemedi (%s): %s", task_id, exc)

    # ── Redis ─────────────────────────────────────────────────────────────

    @staticmethod
    def _redis_key(task_id: str) -> str:
        return f"agent:session:{task_id}"

    async def _redis_set(self, ctx: SessionContext) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set_raw(self._redis_key(ctx.task_id), ctx.to_json(), ttl=SESSION_TTL)
        except Exception as exc:
            logger.debug("Session Redis yazılamadı (%s): %s", ctx.task_id, exc)

    async def _redis_get(self, task_id: str) -> Optional[SessionContext]:
        if not self._redis:
            return None
        try:
            raw = await self._redis.get_raw(self._redis_key(task_id))
            if raw:
                return SessionContext.from_json(raw)
        except Exception as exc:
            logger.debug("Session Redis okunamadı (%s): %s", task_id, exc)
        return None

    # ── PostgreSQL: checkpoint.extra alanı ───────────────────────────────

    async def _pg_save_extra(self, ctx: SessionContext) -> None:
        """Minimal bağlamı agent_checkpoints.extra JSONB'ye yazar."""
        if not self._pool:
            return
        minimal = {
            "step":          ctx.current_step,
            "spec":          ctx.spec[:500] if ctx.spec else "",
            "test_code":     ctx.test_code[:200] if ctx.test_code else "",
            "tokens_used":   ctx.tokens_used,
            "memory_count":  len(ctx.memory_items),
        }
        try:
            await self._pg_execute(
                "UPDATE agent_checkpoints SET extra=$1::jsonb WHERE task_id=$2",
                json.dumps(minimal), ctx.task_id,
            )
        except Exception as exc:
            logger.debug("Session PG extra yazılamadı (%s): %s", ctx.task_id, exc)

    async def _pg_load_extra(self, task_id: str) -> Optional[SessionContext]:
        """agent_checkpoints'ten minimal bağlamla SessionContext oluşturur."""
        if not self._pool:
            return None
        try:
            rows = await self._pg_fetch(
                """SELECT task_id, goal, collection, project_path,
                          step, current_tier, extra
                   FROM agent_checkpoints WHERE task_id=$1""",
                task_id,
            )
            if not rows:
                return None
            row = dict(rows[0])
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                extra = json.loads(extra)
            return SessionContext(
                task_id=row["task_id"],
                goal=row.get("goal", ""),
                collection=row.get("collection", ""),
                project_path=row.get("project_path", ""),
                current_step=row.get("step", "SPEC"),
                tier=row.get("current_tier", "TIER_CHEAP"),
                spec=extra.get("spec", ""),
                test_code=extra.get("test_code", ""),
                tokens_used=extra.get("tokens_used", 0),
            )
        except Exception as exc:
            logger.warning("Session PG yükleme hatası (%s): %s", task_id, exc)
            return None


# Singleton
_store: Optional[SessionContextStore] = None


def get_session_store(redis_store=None, postgres_store=None) -> SessionContextStore:
    global _store
    if _store is None:
        _store = SessionContextStore(redis_store, postgres_store)
    return _store
