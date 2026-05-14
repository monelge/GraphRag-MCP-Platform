from __future__ import annotations

"""Semantik hafıza için episodic store üzerine ince sarmalayıcı."""

from src.memory.models.memory_models import MemoryEntry
from src.memory.stores.episodic_store import EpisodicStore


class SemanticMemoryStore(EpisodicStore):
    """Semantik kayıtları ortak storage altyapısını tekrar etmeden yönetir."""

    async def store_semantic(self, entry: MemoryEntry, redis_store=None) -> str:
        """Kaydı semantic type/layer ile zorlayarak saklar."""
        semantic_entry = MemoryEntry(
            title=entry.title,
            content=entry.content,
            memory_type="semantic",
            tags=entry.tags,
            collection=entry.collection,
            module=entry.module,
            commit_sha=entry.commit_sha,
            provenance=entry.provenance,
            valid_from=entry.valid_from,
            valid_to=entry.valid_to,
            status=entry.status,
            task_id=entry.task_id,
            checkpoint_id=entry.checkpoint_id,
            step_id=entry.step_id,
            entry_id=entry.entry_id,
            created_at=entry.created_at,
        )
        return await super().store_memory(semantic_entry, redis_store=redis_store)

    async def search_semantic(self, query: str, collection: str = "", top_k: int = 5) -> list[dict]:
        """Sadece semantic layer kayıtlarını arar."""
        return await super().search_memory(
            query,
            memory_type="semantic",
            memory_layer="semantic",
            collection=collection or None,
            top_k=top_k,
        )
