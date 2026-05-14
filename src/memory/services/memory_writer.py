from __future__ import annotations

"""Bellek katmanına yalnızca yazma sorumluluğu taşıyan servis."""

import time

from src.memory.models.memory_models import MemoryEntry
from src.memory.stores.decision_store import DecisionStore
from src.memory.stores.episodic_store import EpisodicStore


class MemoryWriter:
    """Handler mantığını bozmadan yazma akışlarını servis seviyesine taşır."""

    def __init__(self, episodic_store: EpisodicStore | None = None):
        self.episodic_store = episodic_store or EpisodicStore()
        self.decision_store = DecisionStore(self.episodic_store)

    async def write(self, entry: MemoryEntry, redis_store=None) -> str:
        """Verilen MemoryEntry kaydını episodic store'a yazar."""
        return await self.episodic_store.store_memory(entry, redis_store=redis_store)

    async def write_decision(
        self,
        title: str,
        content: str,
        collection: str,
        module: str = "",
        commit_sha: str = "",
        provenance: str = "",
        tags: list[str] | None = None,
        valid_days: int | None = None,
        status: str = "active",
    ) -> str:
        """Karar kaydını decision layer altında yazar."""
        valid_to = time.time() + (valid_days * 86400) if valid_days else None
        return await self.decision_store.store_decision(
            title,
            content,
            collection=collection,
            module=module,
            commit_sha=commit_sha,
            provenance=provenance,
            tags=tags or [],
            valid_to=valid_to,
            status=status,
        )
