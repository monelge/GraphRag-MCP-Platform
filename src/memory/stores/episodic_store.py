"""
Episodik hafıza deposu.

Neden ayrı modül?
1. Storage katmanındaki geriye dönük uyumluluğu korur.
2. Memory plane refactor'ını bağımsız ilerletir.
3. Yeni decision/temporal store'lar için ortak temel sağlar.
"""

from __future__ import annotations

import logging
import time

from src.memory.models.memory_models import MemoryEntry, MemoryLayer, MemoryType, _MEMORY_TYPE_TO_LAYER

logger = logging.getLogger(__name__)
_MEMORY_COLLECTION = "episodic_memory"


class EpisodicStore:
    """Qdrant tabanlı episodik hafıza deposu."""

    def __init__(self):
        self._collection = _MEMORY_COLLECTION

    async def _get_store(self):
        from src.storage.qdrant_store import QdrantStore

        store = QdrantStore(collection=self._collection)
        await store.ensure_collection()
        return store

    async def _get_embedders(self, redis_store=None):
        from src.indexing.embedders.dense_embedder import DenseEmbedder
        from src.indexing.embedders.sparse_embedder import SparseEmbedder

        return DenseEmbedder(redis_store=redis_store), SparseEmbedder()

    async def store_memory(self, entry: MemoryEntry, redis_store=None) -> str:
        """Yeni bir hafıza kaydı oluşturur veya günceller."""
        try:
            store = await self._get_store()
            dense, sparse = await self._get_embedders(redis_store)
            text = f"{entry.title}\n\n{entry.content}"
            dense_vecs = await dense.embed_batch([text])
            sparse_vecs = list(sparse.embed_batch([text]))

            from src.indexing.chunkers.chunk_models import CodeChunk

            pseudo_chunk = CodeChunk(
                chunk_id=entry.entry_id,
                file_path=f"memory://{entry.memory_type}/{entry.entry_id}",
                language="markdown",
                chunk_type=entry.memory_type,
                name=entry.title,
                code=entry.content,
                start_line=0,
                end_line=0,
            )
            await store.upsert_chunks(
                [pseudo_chunk],
                dense_vecs,
                sparse_vecs,
                extra_payload={
                    "memory_type": entry.memory_type,
                    "memory_layer": entry.memory_layer,
                    "tags": entry.tags,
                    "collection": entry.collection,
                    "module": entry.module,
                    "commit_sha": entry.commit_sha,
                    "provenance": entry.provenance,
                    "created_at": entry.created_at,
                    "valid_from": entry.valid_from,
                    "valid_to": entry.valid_to,
                    "status": entry.status,
                    "source_type": "episodic_memory",
                    "task_id": entry.task_id,
                    "checkpoint_id": entry.checkpoint_id,
                    "step_id": entry.step_id,
                },
            )
            return f"✅ Bellek kaydı oluşturuldu: {entry.entry_id} ({entry.memory_type}/{entry.memory_layer})"
        except Exception as exc:
            logger.error("EpisodicStore.store_memory hata: %s", exc)
            return f"⚠️ Bellek kaydı oluşturulamadı: {exc}"

    async def search_memory(
        self,
        query: str,
        memory_type: str = None,
        memory_layer: str = None,
        collection: str = None,
        include_invalid: bool = False,
        top_k: int = 5,
    ) -> list[dict]:
        """Bellek kayıtlarında hibrit arama yapar."""
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            from src.retrieval.search.hybrid_search import HybridSearcher

            searcher = HybridSearcher(collection=self._collection)
            must_conditions = [
                FieldCondition(key="source_type", match=MatchValue(value="episodic_memory"))
            ]
            if not include_invalid:
                must_conditions.append(FieldCondition(key="status", match=MatchValue(value="active")))

            effective_layer = memory_layer
            if not effective_layer and memory_type:
                effective_layer = _MEMORY_TYPE_TO_LAYER.get(memory_type)
            if effective_layer:
                must_conditions.append(
                    FieldCondition(key="memory_layer", match=MatchValue(value=effective_layer))
                )
            elif memory_type:
                must_conditions.append(
                    FieldCondition(key="memory_type", match=MatchValue(value=memory_type))
                )
            if collection:
                must_conditions.append(
                    FieldCondition(key="collection", match=MatchValue(value=collection))
                )

            return await searcher.search(query, top_k=top_k, query_filter=Filter(must=must_conditions))
        except Exception as exc:
            logger.debug("EpisodicStore.search_memory hata: %s", exc)
            return []

    async def prune_expired(self, collection: str = None, before_timestamp: float = None) -> int:
        """valid_to < before_timestamp olan aktif kayıtları siler."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
        from src.storage.qdrant_store import QdrantStore

        store = QdrantStore(collection=self._collection)
        await store.ensure_collection()

        must_conditions = [
            FieldCondition(key="source_type", match=MatchValue(value="episodic_memory")),
            FieldCondition(key="status", match=MatchValue(value="active")),
        ]
        if collection:
            must_conditions.append(FieldCondition(key="collection", match=MatchValue(value=collection)))

        # valid_to var olan kayıtları bul (None olanlar expire etmez)
        # Qdrant'ta null payload arama doğrudan yapılamaz; scroll sonrası python filtresi ile
        total_deleted = 0
        offset = None
        while True:
            points, next_offset = await store.client.scroll(
                collection_name=self._collection,
                limit=1000,
                offset=offset,
                with_payload=["valid_to", "collection", "status"],
                with_vectors=False,
            )
            to_delete = []
            for p in points:
                payload = p.payload or {}
                if payload.get("status") != "active":
                    continue
                if collection and payload.get("collection") != collection:
                    continue
                valid_to = payload.get("valid_to")
                if valid_to is not None and valid_to < (before_timestamp or time.time()):
                    to_delete.append(str(p.id))
            if to_delete:
                await store.delete_chunks_by_point_ids(to_delete)
                total_deleted += len(to_delete)
            if next_offset is None or not points:
                break
            offset = next_offset

        return total_deleted
