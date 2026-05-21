from __future__ import annotations

"""Kaynak kodu odaklı yüksek hassasiyetli yerel arama katmanı."""

from qdrant_client.models import FieldCondition, Filter, MatchValue

from src.retrieval.search.hybrid_search import HybridSearcher


class LocalSearcher:
    """Sadece source_code chunk'ları üzerinde hassas arama yapar."""

    def __init__(self, collection: str = "codebase", top_k_fetch: int = 20, redis_store=None):
        self.searcher = HybridSearcher(collection=collection, top_k_fetch=top_k_fetch, redis_store=redis_store)

    async def search(self, query: str, collection: str = "", top_k: int = 5, query_filter=None) -> list[dict]:
        """Belirli dosya veya fonksiyon aramalarında sadece kod chunk'larını döndürür."""
        if collection and collection != self.searcher.store.collection:
            self.searcher = HybridSearcher(
                collection=collection, 
                top_k_fetch=max(top_k * 4, 20), 
                redis_store=self.searcher.dense._redis
            )
        query_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="code"))]
        )
        return await self.searcher.search(
            query,
            top_k=top_k,
            fetch_k=max(top_k * 3, 15),
            query_filter=query_filter,
        )
