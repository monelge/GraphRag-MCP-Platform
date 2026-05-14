from __future__ import annotations

"""Bellek katmanı için yalnızca okuma sorumluluğu taşıyan servis."""

from src.memory.stores.decision_store import DecisionStore
from src.memory.stores.episodic_store import EpisodicStore


class MemoryRecall:
    """Episodik ve karar hafızası için okuma erişimini merkezileştirir."""

    def __init__(self, episodic_store: EpisodicStore | None = None):
        self.episodic_store = episodic_store or EpisodicStore()
        self.decision_store = DecisionStore(self.episodic_store)

    async def recall(
        self,
        query: str,
        memory_type: str | None = None,
        memory_layer: str | None = None,
        collection: str = "",
        include_invalid: bool = False,
        top_k: int = 5,
    ) -> list[dict]:
        """Genel hafıza araması yapar."""
        return await self.episodic_store.search_memory(
            query,
            memory_type=memory_type,
            memory_layer=memory_layer,
            collection=collection or None,
            include_invalid=include_invalid,
            top_k=top_k,
        )

    async def recall_decisions(self, query: str, collection: str = "", top_k: int = 5) -> list[dict]:
        """Decision layer filtreli hafıza araması yapar."""
        return await self.decision_store.search_decisions(query, collection=collection, top_k=top_k)
