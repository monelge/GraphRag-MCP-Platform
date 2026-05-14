"""Zamana duyarlı hafıza kayıtları için yardımcı depo."""

from __future__ import annotations

import time

from src.memory.models.memory_models import MemoryEntry
from src.memory.stores.episodic_store import EpisodicStore


class TemporalStore:
    """Temporal fact yazma ve aktif kayıt okuma işlemlerini toplar."""

    def __init__(self, episodic_store: EpisodicStore):
        self.episodic_store = episodic_store

    async def store_temporal_fact(
        self,
        title: str,
        content: str,
        valid_from: float = None,
        valid_to: float = None,
        **kwargs,
    ) -> str:
        """Geçerlilik aralığı olan hafıza kaydı yazar."""
        entry = MemoryEntry(
            title=title,
            content=content,
            memory_type="episodic",
            valid_from=valid_from or time.time(),
            valid_to=valid_to,
            **kwargs,
        )
        return await self.episodic_store.store_memory(entry)

    async def recall_active_facts(self, query: str, collection: str = "", top_k: int = 5) -> list[dict]:
        """Şu an aktif kabul edilen temporal kayıtları döndürür."""
        now = time.time()
        results = await self.episodic_store.search_memory(
            query,
            collection=collection or None,
            include_invalid=False,
            top_k=top_k,
        )
        active = []
        for item in results:
            valid_to = item.get("valid_to")
            if valid_to is None or valid_to > now:
                active.append(item)
        return active
