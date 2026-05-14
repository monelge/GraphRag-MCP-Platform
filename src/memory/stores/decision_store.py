"""Karar hafızası için ince sarmalayıcı depo."""

from __future__ import annotations

from src.memory.models.memory_models import MemoryEntry
from src.memory.stores.episodic_store import EpisodicStore


class DecisionStore:
    """Decision-memory işlemlerini tek noktadan toplar."""

    def __init__(self, episodic_store: EpisodicStore):
        self.episodic_store = episodic_store

    async def store_decision(self, title: str, content: str, **kwargs) -> str:
        """Karar kaydını decision layer altında saklar."""
        entry = MemoryEntry(title=title, content=content, memory_type="architectural_decision", **kwargs)
        return await self.episodic_store.store_memory(entry)

    async def search_decisions(self, query: str, collection: str = "", top_k: int = 5) -> list[dict]:
        """Decision layer filtreli arama yapar."""
        return await self.episodic_store.search_memory(
            query,
            memory_layer="decision",
            collection=collection or None,
            top_k=top_k,
        )
