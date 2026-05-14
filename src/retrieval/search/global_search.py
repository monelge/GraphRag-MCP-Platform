from __future__ import annotations

"""Mimari ve onboarding bağlamı için repository özeti arama katmanı."""

from qdrant_client.models import FieldCondition, Filter, MatchValue

from src.retrieval.search.hybrid_search import HybridSearcher


class GlobalSearcher:
    """Sadece repo_summary kaynaklarını döndüren global arayıcı."""

    def __init__(self, collection: str = "codebase", top_k_fetch: int = 20):
        self.searcher = HybridSearcher(collection=collection, top_k_fetch=top_k_fetch)

    async def search(self, query: str, collection: str = "", top_k: int = 6, query_filter=None) -> list[dict]:
        """Repository summary chunk'ları üzerinde mimari arama yapar."""
        if collection and collection != self.searcher.store.collection:
            self.searcher = HybridSearcher(collection=collection, top_k_fetch=max(top_k * 3, 18))
        query_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="repo_summary"))]
        )
        return await self.searcher.search(
            query,
            top_k=top_k,
            fetch_k=max(top_k * 2, 12),
            query_filter=query_filter,
        )
