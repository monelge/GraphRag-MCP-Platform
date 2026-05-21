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
        """Decision ve episodic layer filtreli arama yapar (öğrenilen dersleri de kapsar)."""
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        
        # Sadece karar (decision) değil, başarılı adımlardan öğrenilen tecrübeleri (episodic) de dahil et.
        must_conditions = [
            FieldCondition(key="source_type", match=MatchValue(value="episodic_memory")),
            FieldCondition(key="status", match=MatchValue(value="active")),
            FieldCondition(key="memory_layer", match=MatchAny(any=["decision", "episodic"]))
        ]
        if collection:
            must_conditions.append(FieldCondition(key="collection", match=MatchValue(value=collection)))

        from src.retrieval.search.hybrid_search import HybridSearcher
        searcher = HybridSearcher(collection="episodic_memory")
        return await searcher.search(query, top_k=top_k, query_filter=Filter(must=must_conditions))
