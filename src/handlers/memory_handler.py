from __future__ import annotations

import time

from src.handlers.context import AppContext
from src.memory.models.memory_models import MemoryEntry
from src.memory.services.memory_recall import MemoryRecall
from src.memory.services.memory_writer import MemoryWriter
from src.memory.stores.decision_store import DecisionStore
from src.memory.stores.semantic_memory_store import SemanticMemoryStore


class MemoryHandler:
    """Episodik ve karar hafızası araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.decision_store = DecisionStore(ctx.episodic)
        self.memory_writer = MemoryWriter(ctx.episodic)
        self.memory_recall = MemoryRecall(ctx.episodic)
        self.semantic_store = SemanticMemoryStore()

    async def store_memory(self, title: str, content: str, memory_type: str = "general", tags=None, collection: str = "", module: str = "", commit_sha: str = "", provenance: str = "", valid_days: int = None, status: str = "active") -> str:
        valid_to = time.time() + (valid_days * 86400) if valid_days else None
        entry = MemoryEntry(
            title=title,
            content=content,
            memory_type=memory_type,
            tags=tags or [],
            collection=collection,
            module=module,
            commit_sha=commit_sha,
            provenance=provenance,
            valid_to=valid_to,
            status=status,
        )
        if self.ctx.audit_logger:
            await self.ctx.audit_logger.log("memory_write", collection=collection, summary=title)
        if memory_type == "semantic":
            return await self.semantic_store.store_semantic(entry, redis_store=self.ctx.redis)
        return await self.memory_writer.write(entry, redis_store=self.ctx.redis)

    async def recall_memory(self, query: str, memory_type: str = None, memory_layer: str = None, collection: str = "", include_invalid: bool = False, top_k: int = 5) -> str:
        entries = await self.memory_recall.recall(
            query,
            memory_type=memory_type,
            memory_layer=memory_layer,
            collection=collection or None,
            include_invalid=include_invalid,
            top_k=top_k,
        )
        if not entries:
            return "🔍 Episodik hafızada uygun kayıt bulunamadı."
        output = [f"## 🧠 Hafıza Arama: '{query}'\n"]
        for entry in entries:
            content = entry.get("content", entry.get("code", ""))
            output.append(
                f"### [{entry.get('memory_type', '?')}] {entry.get('title', '')} — skor: {entry.get('score', 0):.3f}\n"
                f"{content[:600]}\n"
            )
        return "\n".join(output)

    async def compact_memory(self, collection: str, query: str = "*") -> str:
        from src.memory.services.memory_compaction import MemoryCompactor

        compactor = MemoryCompactor(self.ctx.episodic)
        return await compactor.compact(collection, query)

    async def store_decision_memory(self, title: str, content: str, collection: str, module: str = "", commit_sha: str = "", provenance: str = "", tags=None) -> str:
        return await self.decision_store.store_decision(
            title,
            content,
            collection=collection,
            module=module,
            commit_sha=commit_sha,
            provenance=provenance,
            tags=tags or [],
        )

    async def search_decisions(self, query: str, collection: str = "", top_k: int = 5) -> str:
        entries = await self.decision_store.search_decisions(query, collection, top_k)
        if not entries:
            return "🔍 Karar hafızasında uygun kayıt bulunamadı."
        output = [f"## Karar Hafızası — '{query}'\n"]
        for item in entries:
            output.append(f"### {item.get('title', '')} — skor: {item.get('score', 0):.3f}\n{item.get('content', '')[:800]}\n")
        return "\n".join(output)
