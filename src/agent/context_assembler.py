"""
Context Assembler — GraphRAG + bellek + hibrit etki skoru ile TDAD bağlamı.

CONTEXT adımında çağrılır. Şunları bir araya getirir:
  1. search_code()   — semantik kod arama
  2. recall_memory() — önceki kararlar/başarılar
  3. analyze_change_impact() — etkilenen dosyaları bul
  4. Token bütçesine göre kırpma

Hibrit etki skoru: 0.4×call_graph + 0.3×dep_graph + 0.2×pagerank + 0.1×co_change
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from src.agent.session_context import CodeChunk, SessionContext
from src.agent.spec_builder import TaskSpec
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Hibrit etki ağırlıkları
W_CALL_GRAPH  = float(os.getenv("IMPACT_W_CALL_GRAPH",  "0.40"))
W_DEP_GRAPH   = float(os.getenv("IMPACT_W_DEP_GRAPH",   "0.30"))
W_PAGERANK    = float(os.getenv("IMPACT_W_PAGERANK",    "0.20"))
W_CO_CHANGE   = float(os.getenv("IMPACT_W_CO_CHANGE",   "0.10"))

MAX_SEARCH_RESULTS: int = int(os.getenv("CONTEXT_MAX_SEARCH_RESULTS", "8"))
MAX_MEMORY_RESULTS: int = int(os.getenv("CONTEXT_MAX_MEMORY_RESULTS", "5"))


@dataclass
class ImpactScore:
    file_path:    str
    score:        float   # 0.0–1.0
    call_graph:   float = 0.0
    dep_graph:    float = 0.0
    pagerank:     float = 0.0
    co_change:    float = 0.0

    @classmethod
    def from_impact_data(cls, file_path: str, data: dict) -> "ImpactScore":
        cg  = float(data.get("call_graph_score",    data.get("call_graph",  0)))
        dep = float(data.get("dependency_score",    data.get("dep_graph",   0)))
        pr  = float(data.get("pagerank_score",      data.get("pagerank",    0)))
        cc  = float(data.get("co_change_score",     data.get("co_change",   0)))
        hybrid = (W_CALL_GRAPH*cg + W_DEP_GRAPH*dep + W_PAGERANK*pr + W_CO_CHANGE*cc)
        return cls(file_path=file_path, score=round(hybrid, 4),
                   call_graph=cg, dep_graph=dep, pagerank=pr, co_change=cc)


@dataclass
class AssemblyResult:
    """Context assembler'ın çıktısı."""
    code_chunks:    list[dict]    = field(default_factory=list)
    memory_items:   list[dict]    = field(default_factory=list)
    impact_scores:  list[dict]    = field(default_factory=list)
    tokens_used:    int           = 0
    context_text:   str           = ""
    sources:        list[str]     = field(default_factory=list)


class ContextAssembler:
    """
    GraphRAG araçları ve bellek yöneticisini çağırarak TDAD bağlamı derler.

    mcp_handler: MCP araçlarını çağırabilen obje (search_code, recall_memory, analyze_change_impact)
    """

    def __init__(self, mcp_handler=None) -> None:
        self._mcp = mcp_handler

    async def assemble(
        self,
        spec: TaskSpec,
        ctx: SessionContext,
        token_budget: int,
        widen: bool = False,
    ) -> AssemblyResult:
        """
        Paralel olarak kod araması + bellek sorgusu + etki analizi çalıştırır.
        token_budget: izin verilen toplam token sayısı (widen=True ise 1.5×)
        """
        effective_budget = int(token_budget * 1.5) if widen else token_budget

        # Paralel sorgular
        tasks = [
            self._fetch_code_context(spec, effective_budget),
            self._fetch_memory(spec),
        ]
        if spec.affected_files:
            tasks.append(self._fetch_impact(spec))
        else:
            tasks.append(self._no_impact())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        code_chunks   = results[0] if not isinstance(results[0], Exception) else []
        memory_items  = results[1] if not isinstance(results[1], Exception) else []
        impact_scores = results[2] if not isinstance(results[2], Exception) else []

        if isinstance(results[0], Exception):
            logger.warning("Kod arama hatası: %s", results[0])
        if isinstance(results[1], Exception):
            logger.warning("Bellek sorgu hatası: %s", results[1])

        # SessionContext'e yaz
        for chunk in code_chunks:
            ctx.add_code_chunk(CodeChunk(**chunk))
        for item in memory_items:
            ctx.add_memory_item(item)

        # Bağlam metni
        context_text = ctx.build_context_text(effective_budget)
        tokens_used = len(context_text) // 4

        sources = ["search_code"] + (["recall_memory"] if memory_items else [])
        if impact_scores:
            sources.append("analyze_change_impact")

        logger.info(
            "ContextAssembler: chunks=%d memory=%d impact=%d tokens≈%d",
            len(code_chunks), len(memory_items), len(impact_scores), tokens_used,
        )
        return AssemblyResult(
            code_chunks=code_chunks,
            memory_items=memory_items,
            impact_scores=[s if isinstance(s, dict) else vars(s) for s in impact_scores],
            tokens_used=tokens_used,
            context_text=context_text,
            sources=sources,
        )

    # ── MCP çağrıları ─────────────────────────────────────────────────────

    async def _fetch_code_context(
        self, spec: TaskSpec, token_budget: int
    ) -> list[dict]:
        chunks: list[dict] = []
        if not self._mcp:
            return chunks

        queries = spec.search_queries[:3] or [spec.goal[:120]]

        for query in queries:
            try:
                result = await self._mcp.search_code(
                    query=query,
                    collection=spec.collection,
                    limit=MAX_SEARCH_RESULTS,
                )
                items = self._parse_search_result(result, query)
                chunks.extend(items)
                if len(chunks) >= MAX_SEARCH_RESULTS:
                    break
            except Exception as exc:
                logger.debug("search_code hatası (query='%s'): %s", query[:40], exc)

        # Eğer search_code yetersizse grep_exact_string dene
        if not chunks and spec.affected_files:
            for sym in spec.affected_symbols[:2]:
                try:
                    result = await self._mcp.grep_exact_string(
                        query=sym,
                        collection=spec.collection,
                    )
                    items = self._parse_search_result(result, sym)
                    chunks.extend(items)
                except Exception as exc:
                    logger.debug("grep_exact_string hatası: %s", exc)

        return chunks[:MAX_SEARCH_RESULTS]

    async def _fetch_memory(self, spec: TaskSpec) -> list[dict]:
        if not self._mcp:
            return []
        items: list[dict] = []
        try:
            result = await self._mcp.recall_memory(
                query=spec.goal[:120],
                collection=spec.collection,
                limit=MAX_MEMORY_RESULTS,
            )
            items = self._parse_memory_result(result)
        except Exception as exc:
            logger.debug("recall_memory hatası: %s", exc)
        return items

    async def _fetch_impact(self, spec: TaskSpec) -> list[ImpactScore]:
        if not self._mcp:
            return []
        try:
            result = await self._mcp.analyze_change_impact(
                project_path=spec.project_path,
                changed_paths=spec.affected_files[:5],
                collection=spec.collection,
            )
            return self._parse_impact_result(result, spec.affected_files)
        except Exception as exc:
            logger.debug("analyze_change_impact hatası: %s", exc)
            return []

    @staticmethod
    async def _no_impact() -> list:
        return []

    # ── Parse yardımcıları ─────────────────────────────────────────────────

    @staticmethod
    def _parse_search_result(result: Any, query: str) -> list[dict]:
        chunks = []
        if result is None:
            return chunks
        # MCP sonuç formatını normalize et
        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = result.get("results", result.get("items", result.get("chunks", [])))
            if isinstance(items, str):
                # Ham metin döndüyse tek chunk olarak ekle
                return [{"file_path": "search_result", "content": items[:2000], "relevance": 1.0}]

        for item in items[:MAX_SEARCH_RESULTS]:
            if isinstance(item, dict):
                chunks.append({
                    "file_path": item.get("file_path", item.get("path", "unknown")),
                    "content":   item.get("content", item.get("text", str(item)))[:1500],
                    "relevance": float(item.get("score", item.get("relevance", 0.8))),
                    "source":    "search_code",
                })
            elif isinstance(item, str):
                chunks.append({"file_path": "search", "content": item[:1500], "relevance": 0.7, "source": "search_code"})
        return chunks

    @staticmethod
    def _parse_memory_result(result: Any) -> list[dict]:
        if result is None:
            return []
        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = result.get("memories", result.get("results", result.get("items", [])))
        return [
            {
                "title":   m.get("title", "Bellek") if isinstance(m, dict) else "Bellek",
                "content": m.get("content", str(m))[:500] if isinstance(m, dict) else str(m)[:500],
            }
            for m in items[:MAX_MEMORY_RESULTS]
        ]

    @staticmethod
    def _parse_impact_result(result: Any, files: list[str]) -> list[ImpactScore]:
        if result is None:
            return []
        scores = []
        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = result.get("affected_files", result.get("files", result.get("impacts", [])))

        for item in items:
            if isinstance(item, dict):
                fp = item.get("file_path", item.get("path", "unknown"))
                scores.append(ImpactScore.from_impact_data(fp, item))
            elif isinstance(item, str):
                scores.append(ImpactScore(file_path=item, score=0.5))

        # Belirtilen dosyalar impact'ta yoksa ekle
        existing = {s.file_path for s in scores}
        for fp in files:
            if fp not in existing:
                scores.append(ImpactScore(file_path=fp, score=0.3))

        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[:10]


# Singleton
_assembler: Optional[ContextAssembler] = None


def get_context_assembler(mcp_handler=None) -> ContextAssembler:
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler(mcp_handler)
    elif mcp_handler and _assembler._mcp is None:
        _assembler._mcp = mcp_handler
    return _assembler
