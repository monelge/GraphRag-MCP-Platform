"""
Patch Memory — başarılı kod patch'lerini Qdrant + PostgreSQL'e kaydeder.

Feature flag: PATCH_MEMORY_ENABLED=true (varsayılan: false)

Akış:
  COMMIT adımı tamamlandığında → PatchMemoryStore.store_patch()
  CONTEXT adımı başında        → PatchMemoryStore.recall_similar()
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from src.memory.models.memory_models import MemoryEntry
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

PATCH_MEMORY_ENABLED: bool = os.getenv("PATCH_MEMORY_ENABLED", "false").lower() == "true"
PATCH_CONTENT_MAX_CHARS = 4000
VERIFY_OUTPUT_MAX_CHARS = 500


@dataclass
class PatchRecord:
    """Bir TDAD görevinde uygulanan ve doğrulanan kod değişikliğinin kaydı."""
    task_id:             str
    goal:                str
    task_type:           str          # bugfix | refactor | feature | test | security | docs
    language:            str          # python | typescript | go | java | ...
    patch_content:       str          # unified diff
    affected_files:      list[str]    = field(default_factory=list)
    affected_symbols:    list[str]    = field(default_factory=list)
    acceptance_criteria: list[str]    = field(default_factory=list)
    tier:                str          = "TIER_CHEAP"
    reflection_count:    int          = 0
    commit_hash:         str          = ""
    verify_output:       str          = ""
    collection:          str          = "warelogisticcbys"
    created_at:          float        = field(default_factory=time.time)

    @property
    def patch_hash(self) -> str:
        return hashlib.sha256(self.patch_content.encode()).hexdigest()[:16]


def _format_content(record: PatchRecord) -> str:
    """LLM prompt'unda okunabilir patch bloğu üretir."""
    symbols = ", ".join(record.affected_symbols[:5]) or "—"
    files   = ", ".join(record.affected_files[:3]) or "—"
    patch   = record.patch_content[:PATCH_CONTENT_MAX_CHARS]
    verify  = record.verify_output[:VERIFY_OUTPUT_MAX_CHARS]
    criteria = "\n".join(f"- {c}" for c in record.acceptance_criteria) or "—"

    return (
        f"## Goal\n{record.goal}\n\n"
        f"## Affected\n"
        f"- Files: {files}\n"
        f"- Symbols: {symbols}\n"
        f"- Tier: {record.tier} | Reflections: {record.reflection_count}\n\n"
        f"## Patch ({record.language})\n"
        f"```diff\n{patch}\n```\n\n"
        f"## Verified\n{verify}\n\n"
        f"## Acceptance Criteria\n{criteria}\n"
    )


class PatchMemoryStore:
    """
    Patch'leri Qdrant (hybrid embed) + PostgreSQL (audit) katmanına yazar.

    episodic_store: EpisodicStore nesnesi.
    pg_store:       PostgresStore nesnesi (opsiyonel; None ise PG yazma atlanır).
    """

    def __init__(self, episodic_store=None, pg_store=None) -> None:
        self._episodic = episodic_store
        self._pg       = pg_store

    async def store_patch(self, record: PatchRecord) -> str:
        """
        Patch'i Qdrant ve PG'ye yazar.
        Boş patch veya duplicate (aynı hash) ise atlanır.
        Döner: entry_id (qdrant) veya "" (atlandı/hata).
        """
        if not record.patch_content or not record.patch_content.strip():
            logger.debug("store_patch: boş patch — atlandı (task=%s)", record.task_id)
            return ""

        entry = MemoryEntry(
            title=f"[{record.task_type.upper()}] {record.language}: {record.goal[:60]}",
            content=_format_content(record),
            memory_type="code_patch",
            tags=[record.task_type, record.language, "patch"],
            collection=record.collection,
            commit_sha=record.commit_hash,
            provenance=f"agent-{record.tier}",
            task_id=record.task_id,
            status="active",
        )

        # Qdrant'a yaz
        entry_id = ""
        if self._episodic:
            try:
                result = await self._episodic.store_memory(entry)
                entry_id = entry.entry_id
                logger.info("PatchMemory stored in Qdrant: %s", entry_id)
            except Exception as exc:
                logger.warning("PatchMemory Qdrant yazma hatası: %s", exc)

        # PostgreSQL'e yaz (audit)
        await self._pg_insert(record)
        return entry_id

    async def recall_similar(
        self,
        goal:       str,
        task_type:  str  = "",
        language:   str  = "python",
        collection: str  = "",
        limit:      int  = 3,
    ) -> list[PatchRecord]:
        """
        Benzer patch'leri Qdrant hybrid search ile bulur.
        memory_type="code_patch" filtresi uygular.
        """
        if not self._episodic:
            return []
        try:
            results = await self._episodic.search_memory(
                query=goal,
                memory_type="code_patch",
                collection=collection or None,
                top_k=limit,
            )
            return [_result_to_patch_record(r) for r in results if r]
        except Exception as exc:
            logger.warning("PatchMemory recall hatası: %s", exc)
            return []

    # ── PostgreSQL yardımcıları ────────────────────────────────────────────

    async def _pg_insert(self, record: PatchRecord) -> None:
        if not self._pg:
            return
        pool = getattr(self._pg, "_pool", None)
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO patch_memories
                        (task_id, patch_hash, task_type, language, collection,
                         commit_sha, affected_files, affected_symbols,
                         patch_content, tier, reflection_count)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (patch_hash) DO NOTHING
                    """,
                    record.task_id,
                    record.patch_hash,
                    record.task_type,
                    record.language,
                    record.collection,
                    record.commit_hash,
                    record.affected_files,
                    record.affected_symbols,
                    record.patch_content[:PATCH_CONTENT_MAX_CHARS],
                    record.tier,
                    record.reflection_count,
                )
        except Exception as exc:
            logger.warning("PatchMemory PG insert hatası: %s", exc)


def _result_to_patch_record(result: dict) -> Optional[PatchRecord]:
    """Qdrant arama sonucunu PatchRecord'a dönüştürür."""
    try:
        payload = result.get("payload", result)
        return PatchRecord(
            task_id=payload.get("task_id", ""),
            goal=payload.get("name", payload.get("title", "")),
            task_type=payload.get("chunk_type", "unknown"),
            language=payload.get("language", "python"),
            patch_content=payload.get("code", ""),
            collection=payload.get("collection", ""),
            commit_hash=payload.get("commit_sha", ""),
            tier=payload.get("provenance", "").replace("agent-", "") or "TIER_CHEAP",
        )
    except Exception:
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: Optional[PatchMemoryStore] = None


def get_patch_memory_store(episodic_store=None, pg_store=None) -> PatchMemoryStore:
    global _store
    if _store is None:
        if episodic_store is None:
            try:
                from src.memory.stores.episodic_store import EpisodicStore
                episodic_store = EpisodicStore()
            except ImportError:
                pass
        _store = PatchMemoryStore(episodic_store=episodic_store, pg_store=pg_store)
    return _store


def reset_patch_memory_store() -> None:
    """Test'lerde singleton'ı sıfırlamak için."""
    global _store
    _store = None
