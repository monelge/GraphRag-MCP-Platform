from __future__ import annotations

import time

from src.handlers.context import AppContext
from src.storage.episodic_store import MemoryEntry


class MemoryHandler:
    """Episodik ve karar hafızası araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    async def store_memory(
        self,
        title: str,
        content: str,
        memory_type: str = "general",
        tags: list[str] | None = None,
        collection: str = "",
        module: str = "",
        commit_sha: str = "",
        provenance: str = "",
        valid_days: int | None = None,
        status: str = "active",
    ) -> str:
        """Yeni bir episodik hafıza kaydı yazar."""
        valid_to = None
        if valid_days:
            valid_to = time.time() + (valid_days * 86400)

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
        return await self.ctx.episodic.store_memory(entry, redis_store=self.ctx.redis)

    async def recall_memory(
        self,
        query: str,
        memory_type: str | None = None,
        memory_layer: str | None = None,
        collection: str = "",
        include_invalid: bool = False,
        top_k: int = 5,
    ) -> str:
        """Hafıza kayıtlarında arama yapar."""
        entries = await self.ctx.episodic.search_memory(
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
            tags_str = " ".join(f"`{tag}`" for tag in entry.get("tags", []))
            stat_note = ""
            status = entry.get("status")
            if status and status != "active":
                stat_note = f" [⚠️ {status.upper()}]"

            content = entry.get("content", entry.get("code", ""))
            output.append(
                f"### [{entry.get('memory_type', '?')}] {entry['title']}{stat_note} — skor: {entry.get('score', 0):.3f}\n"
                + (f"🏷️ {tags_str}\n" if tags_str else "")
                + (f"📦 Koleksiyon: `{entry.get('collection', '')}`\n" if entry.get("collection") else "")
                + (f"🧩 Modül: `{entry.get('module', '')}`\n" if entry.get("module") else "")
                + (f"🔖 Commit: `{entry.get('commit_sha', '')}`\n" if entry.get("commit_sha") else "")
                + f"{content[:600]}\n"
            )
        return "\n".join(output)

    async def compact_memory(self, collection: str, query: str = "*") -> str:
        """Benzer hafıza kayıtlarını compaction ile birleştirir."""
        from src.memory.services.memory_compaction import MemoryCompactor

        compactor = MemoryCompactor(self.ctx.episodic)
        return await compactor.compact(collection, query)

    async def store_decision_memory(
        self,
        title: str,
        content: str,
        collection: str,
        module: str = "",
        commit_sha: str = "",
        provenance: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """Karar hafızasına yeni kayıt yazar."""
        entry = MemoryEntry(
            title=title,
            content=content,
            memory_type="decision",
            tags=tags or [],
            collection=collection,
            module=module,
            commit_sha=commit_sha,
            provenance=provenance,
        )
        return await self.ctx.episodic.store_memory(entry, redis_store=self.ctx.redis)

    async def search_decisions(
        self,
        query: str,
        collection: str = "",
        top_k: int = 5,
    ) -> str:
        """Karar hafızasında arama yapar."""
        entries = await self.ctx.episodic.search_memory(
            query,
            memory_layer="decision",
            collection=collection or None,
            top_k=top_k,
        )
        if not entries:
            return "🔍 Karar hafızasında uygun kayıt bulunamadı."

        output = [f"## Karar Hafızası — '{query}'\n"]
        for item in entries:
            output.append(
                f"### {item.get('title', '')} — skor: {item.get('score', 0):.3f}\n"
                + (f"📦 Koleksiyon: `{item.get('collection', '')}`\n" if item.get("collection") else "")
                + (f"🧩 Modül: `{item.get('module', '')}`\n" if item.get("module") else "")
                + (f"🔖 Commit: `{item.get('commit_sha', '')}`\n" if item.get("commit_sha") else "")
                + f"{item.get('content', '')[:800]}\n"
            )
        return "\n".join(output)
