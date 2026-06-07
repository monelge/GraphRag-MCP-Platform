"""
MCP Bridge — GraphRagMCP araçlarını CodeActRunner'dan çağırmak için köprü.

MCP SSE transport yerine doğrudan Python fonksiyon çağrısı yapar;
production'da import yolu ile handler fonksiyonlarına erişir.
"""

from __future__ import annotations

from typing import Any, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class MCPBridge:
    """
    MCP tool_registry fonksiyonlarını sararak ContextAssembler için
    tek bir interface sunar.
    """

    def __init__(self) -> None:
        self._registry = self._load_registry()

    def _load_registry(self) -> dict:
        try:
            from src.mcp.tool_registry import (
                analyze_change_impact,
                grep_exact_string,
                recall_memory,
                search_code,
                store_memory,
            )
            return {
                "search_code":           search_code,
                "grep_exact_string":     grep_exact_string,
                "recall_memory":         recall_memory,
                "store_memory":          store_memory,
                "analyze_change_impact": analyze_change_impact,
            }
        except ImportError as exc:
            logger.warning("MCP tool_registry yüklenemedi: %s", exc)
            return {}

    async def search_code(
        self, query: str, collection: str, limit: int = 8
    ) -> Any:
        fn = self._registry.get("search_code")
        if fn is None:
            return []
        return await fn(query=query, collection=collection, limit=limit)

    async def grep_exact_string(
        self, query: str, collection: str
    ) -> Any:
        fn = self._registry.get("grep_exact_string")
        if fn is None:
            return []
        return await fn(query=query, collection=collection)

    async def recall_memory(
        self, query: str, collection: str, limit: int = 5
    ) -> Any:
        fn = self._registry.get("recall_memory")
        if fn is None:
            return []
        return await fn(query=query, collection=collection)

    async def store_memory(
        self, title: str, content: str, collection: str = "agent_learning"
    ) -> Any:
        fn = self._registry.get("store_memory")
        if fn is None:
            return None
        return await fn(title=title, content=content, collection=collection)

    async def analyze_change_impact(
        self,
        project_path: str,
        changed_paths: list[str],
        collection: str,
    ) -> Any:
        fn = self._registry.get("analyze_change_impact")
        if fn is None:
            return {}
        return await fn(
            project_path=project_path,
            changed_paths=changed_paths,
            collection=collection,
        )

    async def recall_patch_examples(
        self,
        goal:       str,
        task_type:  str = "",
        collection: str = "",
        limit:      int = 3,
    ) -> list[dict]:
        """PATCH_MEMORY_ENABLED=true ise benzer geçmiş patch örneklerini döner."""
        import os
        if os.getenv("PATCH_MEMORY_ENABLED", "false").lower() != "true":
            return []
        try:
            from src.agent.patch_memory import get_patch_memory_store
            records = await get_patch_memory_store().recall_similar(
                goal=goal,
                task_type=task_type,
                language="python",
                collection=collection,
                limit=limit,
            )
            return [
                {"goal": r.goal, "patch": r.patch_content[:500],
                 "tier": r.tier, "task_type": r.task_type}
                for r in records
            ]
        except Exception as exc:
            logger.debug("recall_patch_examples hatası: %s", exc)
            return []
