from __future__ import annotations

import json as _json
import logging
import os
import time

from src.shared.config import config
logger = logging.getLogger(__name__)

from src.control.models.guardrail import GuardrailError, RequestBudget, fail_fast_token
from src.control.models.model_router import get_model
from src.handlers.context import AppContext
from src.indexing.embedders.dense_embedder import DenseEmbedder
from src.retrieval.context.compressor import compress_all as compress_chunks
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.token_budget import get_budget_chars
from src.retrieval.ranking.answerability import Confidence, assess as assess_answerability
from src.retrieval.search.graph_expansion import GraphExpander
from src.retrieval.search.global_search import GlobalSearcher
from src.retrieval.search.hybrid_search import (
    CODE_ONLY_FILTER,
    Filter as QFilter,
    FieldCondition as QFC,
    HybridSearcher,
    MatchValue as QMV,
)
from src.retrieval.search.hyde import expand_query as hyde_expand, hyde_retrieve
from src.retrieval.search.local_search import LocalSearcher
from src.retrieval.search.query_classifier import TOP_K_BY_TYPE, classify as classify_query, should_rewrite
from src.shared.llm_client import get_llm_client


class RetrievalHandler:
    """Kod ve mimari retrieval araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    async def search_code(
        self,
        query: str,
        collection: str = "",
        top_k: int = 0,
        rewrite_query: bool | None = None,
    ) -> str:
        """Tam retrieval pipeline ile kod araması yapar."""
        collection = collection or config.default_collection
        t0 = time.monotonic()
        budget = RequestBudget()
        query_type = classify_query(query)
        tracer = self.ctx.tracer(query=query, collection=collection, query_type=query_type)

        if top_k == 0:
            top_k = TOP_K_BY_TYPE[query_type]

        cached = await self.ctx.redis.get_retrieval(collection, query)
        if cached is not None:
            logger.info("retrieval cache hit, pool=%s", bool(self.ctx.postgres._pool))
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                query_type=f"{query_type}:exact_cache",
                cache_hit=True,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return cached

        dense_embedder = DenseEmbedder(redis_store=self.ctx.redis)
        query_emb = (await dense_embedder.embed_batch([query]))[0]
        similar_hash = await self.ctx.redis.find_similar_cached_query(collection, query_emb)
        if similar_hash:
            semantic_key = f"__hash__:{similar_hash}"
            sem_cached = await self.ctx.redis.get_retrieval(collection, semantic_key)
            if sem_cached:
                await self.ctx.postgres.log_retrieval(
                    collection=collection,
                    redacted_query=query[:80],
                    query_type=f"{query_type}:semantic_cache",
                    cache_hit=True,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
                return sem_cached

        await self.ctx.redis.set_query_embedding(collection, query, query_emb)

        effective_query = query
        do_rewrite = rewrite_query if rewrite_query is not None else should_rewrite(query)
        expansions: list[str] = []
        if do_rewrite:
            try:
                budget.consume_aux_llm("query_rewrite_or_hyde")
                client = get_llm_client()
                with tracer.step("hyde"):
                    expansions = await hyde_expand(
                        query,
                        llm_client=client,
                        model=get_model("query_rewrite"),
                    )
                    tracer.record("hyde", item_count=len(expansions))
                if expansions:
                    effective_query = expansions[0]
            except GuardrailError:
                pass
            except Exception:
                effective_query = query

        if query_type in ("factual_doc", "config_lookup"):
            searcher = LocalSearcher(collection=collection, redis_store=self.ctx.redis)
            search_mode = "local"
        elif query_type == "broad_summary":
            searcher = GlobalSearcher(collection=collection, redis_store=self.ctx.redis)
            search_mode = "global"
        else:
            searcher = HybridSearcher(collection=collection, redis_store=self.ctx.redis)
            search_mode = "hybrid"

        with tracer.step("retrieval"):
            if expansions and search_mode == "hybrid":
                candidates = await hyde_retrieve(
                    query=query,
                    expansions=expansions,
                    searcher=searcher,
                    query_filter=CODE_ONLY_FILTER,
                    top_k=top_k,
                )
            elif expansions:
                seen: dict[str, dict] = {}
                for current_query in [query] + (expansions or []):
                    batch = await searcher.search(current_query, collection=collection, top_k=top_k)
                    for chunk in batch:
                        key = f"{chunk.get('file', '')}:{chunk.get('name', '')}:{chunk.get('lines', '')}"
                        existing = seen.get(key)
                        if existing is None or float(chunk.get('score', 0.0) or 0.0) > float(existing.get('score', 0.0) or 0.0):
                            seen[key] = chunk
                candidates = sorted(seen.values(), key=lambda item: float(item.get('score', 0.0) or 0.0), reverse=True)[: top_k * 2]
            elif search_mode == "hybrid":
                candidates = await searcher.search(
                    effective_query,
                    top_k=top_k,
                    fetch_k=top_k * 2,
                    query_filter=CODE_ONLY_FILTER,
                )
            else:
                candidates = await searcher.search(effective_query, collection=collection, top_k=top_k)
            tracer.record("retrieval", item_count=len(candidates))

        if not candidates:
            try:
                await self.ctx.postgres.log_retrieval(
                    collection=collection,
                    redacted_query=query[:80],
                    query_type=query_type,
                    top_k=top_k,
                    hit_count=0,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    answerability_fail=True,
                )
            except Exception as e:
                logger.debug("Postgres log_retrieval başarısız: %s", e)
            return "🔍 Sorguya uygun kod bloğu bulunamadı."

        expander = GraphExpander(self.ctx.neo4j)
        with tracer.step("graph_augment"):
            candidates = await expander.augment_candidates(
                query=query,
                collection=collection,
                normal_candidates=candidates,
                query_type=query_type,
                top_k=top_k,
            )
            tracer.record("graph_augment", item_count=len(candidates))

        rerank_started = time.monotonic()
        with tracer.step("rerank"):
            reranked = self.ctx.reranker.rerank(query, candidates, top_n=top_k)
            tracer.record("rerank", item_count=len(reranked))
        rerank_ms = int((time.monotonic() - rerank_started) * 1000)

        with tracer.step("dedup"):
            deduped = self.ctx.deduplicator.deduplicate(reranked)
            tracer.record("dedup", item_count=len(deduped))

        with tracer.step("graph_expand"):
            entrypoints = [candidate.get("name", "") for candidate in deduped if candidate.get("name")]
            graph_nodes = await expander.expand(entrypoints)
            centrality = await expander.get_centrality(graph_nodes)
            for candidate in deduped:
                candidate["graph_centrality"] = centrality.get(candidate.get("name", ""), 0.0)
            tracer.record("graph_expand", item_count=len(graph_nodes))

        assessment = assess_answerability(deduped, query_type=query_type)
        if assessment.confidence == Confidence.INSUFFICIENT:
            tracer.finish()
            logger.info("retrieval_log yazılıyor (INSUFFICIENT), pool=%s", bool(self.ctx.postgres._pool))
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                query_type=query_type,
                top_k=top_k,
                top1_score=assessment.top1_score,
                latency_ms=int((time.monotonic() - t0) * 1000),
                rerank_latency_ms=rerank_ms,
                answerability_fail=True,
            )
            return f"⚠️ Retrieval yetersiz: {assessment.reason}"

        budget_chars = get_budget_chars(query_type)
        try:
            fail_fast_token(budget_chars // 4, context=f"search_code:{query_type}")
        except GuardrailError as exc:
            return f"⚠️ Token limiti: {exc}"

        builder = ContextBuilder(token_budget=budget_chars // 4, query_type=query_type)
        final_chunks = builder.build(deduped)

        with tracer.step("compress"):
            final_chunks = compress_chunks(final_chunks)
            total_chars = sum(len(chunk.get("code") or chunk.get("content") or "") for chunk in final_chunks)
            tracer.record("compress", token_count=total_chars // 4)

        header = f"## '{query}' için Sonuçlar ({len(final_chunks)} blok)"
        if do_rewrite and expansions:
            header += f"\n> 🔍 HyDE expansion: _{', '.join(expansions[:2])}_"
        if assessment.confidence.value == "weak":
            header += f"\n> ⚠️ {assessment.reason}"

        if self.ctx.audit_logger:
            try:
                await self.ctx.audit_logger.log(
                    "retrieval_request",
                    collection=collection,
                    summary=f"query_type={query_type} top_k={top_k} hits={len(final_chunks)}",
                )
            except Exception as e:
                logger.debug("Audit log başarısız: %s", e)
        if self.ctx.metrics:
            try:
                self.ctx.metrics.record_retrieval(
                    collection,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    hit_count=len(final_chunks),
                    token_count=total_chars // 4,
                )
            except Exception as e:
                logger.debug("Metrics record başarısız: %s", e)

        output = [header + "\n"]
        for result in final_chunks:
            final_score = result.get("final_score", result.get("score", 0.0))
            compression_ratio = result.get("_compression_ratio")
            compression_note = f" 📦 {compression_ratio:.0%}" if compression_ratio and compression_ratio < 1.0 else ""
            output.append(
                f"### `{result['name']}` ({result['type']}) — final_score: {final_score:.3f}{compression_note}\n"
                f"📄 `{result['file']}` satır {result['lines']}\n"
                f"```{result['language']}\n{result['code'][:800]}\n```\n"
            )
        result_text = "\n".join(output)

        await self.ctx.redis.set_retrieval(collection, query, result_text)
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info("retrieval_log yazılıyor (normal), pool=%s", bool(self.ctx.postgres._pool))
        try:
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                query_type=query_type,
                top_k=top_k,
                hit_count=len(final_chunks),
                top1_score=assessment.top1_score,
                latency_ms=latency_ms,
                rerank_latency_ms=rerank_ms,
                token_usage=total_chars // 4,
                cache_hit=False,
                answerability_fail=assessment.is_failure,
            )
        except Exception as e:
            logger.debug("Final log_retrieval başarısız: %s", e)
        return result_text

    async def explain_code(self, query: str, collection: str = "", top_k: int = 5) -> str:
        """Kod bloklarını hibrit arama + LLM analizi ile açıklar."""
        t0 = time.monotonic()
        collection = collection or config.default_collection
        query_type = classify_query(query)

        searcher = HybridSearcher(collection=collection, redis_store=self.ctx.redis)
        candidates = await searcher.search(
            query,
            top_k=top_k * 2,
            fetch_k=top_k * 3,
            query_filter=CODE_ONLY_FILTER,
        )
        if not candidates:
            try:
                await self.ctx.postgres.log_retrieval(
                    collection=collection,
                    redacted_query=query[:80],
                    query_type=query_type,
                    top_k=top_k,
                    hit_count=0,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    answerability_fail=True,
                )
            except Exception as e:
                logger.debug("Postgres log_retrieval başarısız: %s", e)
            return "🔍 Sorguya uygun kod bloğu bulunamadı."

        reranked = self.ctx.reranker.rerank(query, candidates, top_n=top_k)
        deduped = self.ctx.deduplicator.deduplicate(reranked)

        expander = GraphExpander(self.ctx.neo4j)
        entrypoints = [candidate.get("name", "") for candidate in deduped if candidate.get("name")]
        graph_nodes = await expander.expand(entrypoints)
        centrality = await expander.get_centrality(graph_nodes)
        for candidate in deduped:
            candidate["graph_centrality"] = centrality.get(candidate.get("name", ""), 0.0)

        assessment = assess_answerability(deduped)
        if assessment.confidence == Confidence.INSUFFICIENT:
            if self.ctx.postgres:
                await self.ctx.postgres.log_retrieval(
                    collection=collection,
                    redacted_query=query[:80],
                    query_type=query_type,
                    top_k=top_k,
                    top1_score=assessment.top1_score,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    answerability_fail=True,
                )
            return f"⚠️ Retrieval yetersiz: {assessment.reason}"

        budget_chars = get_budget_chars(query_type)
        builder = ContextBuilder(token_budget=budget_chars // 4, query_type=query_type)
        final_chunks = builder.build(deduped)

        model_task = "architecture" if query_type == "broad_summary" else "explain"
        model = get_model(model_task)
        code_context = "\n\n".join(
            [
                f"### {chunk['name']} ({chunk.get('type', '')}) — {chunk['file']} satır {chunk['lines']}\n"
                f"```{chunk['language']}\n{chunk['code'][:700]}\n```"
                for chunk in final_chunks
            ]
        )

        client = get_llm_client()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen uzman bir yazılım mimarısın. "
                        "Verilen kod bloklarını analiz ederek YALNIZCA geçerli JSON döndür. "
                        "Şema:\n"
                        '{"purpose":"","entrypoints":[],"dependencies":[],"flow_summary":[],"security_risks":[],"side_effects":[],"related_components":[]}\n'
                        "Tüm değerler Türkçe olsun. JSON dışında hiçbir şey yazma."
                    ),
                },
                {"role": "user", "content": f"Soru: {query}\n\nKod:\n{code_context}"},
            ],
            max_tokens=1800,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        try:
            parsed = _json.loads(raw)
            output_lines = [f"## 🔍 `{query}` — Kod Analizi\n"]
            if parsed.get("purpose"):
                output_lines.append(f"**Amaç:** {parsed['purpose']}\n")
            if parsed.get("entrypoints"):
                output_lines.append(
                    "**Giriş Noktaları:** " + ", ".join(f"`{entry}`" for entry in parsed["entrypoints"])
                )
            if parsed.get("dependencies"):
                output_lines.append(
                    "**Bağımlılıklar:** "
                    + ", ".join(f"`{dependency}`" for dependency in parsed["dependencies"])
                )
            if parsed.get("flow_summary"):
                output_lines.append("\n**Akış:**")
                for step in parsed["flow_summary"]:
                    output_lines.append(f"  {step}")
            if parsed.get("security_risks"):
                output_lines.append("\n**⚠️ Güvenlik Riskleri:**")
                for risk in parsed["security_risks"]:
                    output_lines.append(f"  - {risk}")
            if parsed.get("side_effects"):
                output_lines.append("\n**Yan Etkiler:** " + "; ".join(parsed["side_effects"]))
            if parsed.get("related_components"):
                output_lines.append(
                    "**İlgili Bileşenler:** "
                    + ", ".join(f"`{component}`" for component in parsed["related_components"])
                )
            if assessment.confidence.value == "weak":
                output_lines.append(f"\n> ⚠️ {assessment.reason}")

            output_lines.append("\n---\n## 📄 Kaynak Kod Blokları\n")
            for chunk in final_chunks:
                output_lines.append(
                    f"### `{chunk['name']}` ({chunk['type']}) — {chunk['file']} satır {chunk['lines']}\n"
                    f"```{chunk['language']}\n{chunk['code'][:800]}\n```\n"
                )
            result = "\n".join(output_lines)
        except Exception:
            result = f"## Kod Analizi: '{query}'\n\n{raw}"

        if self.ctx.postgres:
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                query_type=query_type,
                top_k=top_k,
                hit_count=len(final_chunks),
                top1_score=assessment.top1_score,
                latency_ms=int((time.monotonic() - t0) * 1000),
                cache_hit=False,
            )
        return result

    async def search_repo_architecture(
        self,
        query: str,
        collection: str = "",
        top_k: int = 6,
    ) -> str:
        """Repo summary chunk'ları üzerinden mimari arama yapar."""
        t0 = time.monotonic()
        collection = collection or config.default_collection
        architecture_filter = QFilter(
            must=[QFC(key="source_type", match=QMV(value="repo_summary"))]
        )
        searcher = HybridSearcher(collection=collection, redis_store=self.ctx.redis)
        results = await searcher.search(
            query,
            top_k=top_k,
            fetch_k=max(top_k * 2, 10),
            query_filter=architecture_filter,
        )

        if not results:
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                query_type="architecture",
                top_k=top_k,
                hit_count=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                answerability_fail=True,
            )
            return (
                "🔍 Repository architecture summary bulunamadı. "
                "Önce summarize_repository veya index_project çalıştırın."
            )

        output = [f"## Repository Architecture — `{query}` ({collection})\n"]
        for item in results:
            output.append(
                f"### `{item.get('name', '')}` ({item.get('type', '')}) — skor: {item.get('score', 0):.3f}\n"
                f"{item.get('code', '')[:1200]}\n"
            )
        
        result_text = "\n".join(output)
        await self.ctx.postgres.log_retrieval(
            collection=collection,
            redacted_query=query[:80],
            query_type="architecture",
            top_k=top_k,
            hit_count=len(results),
            top1_score=results[0].get("score", 0.0) if results else 0.0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            cache_hit=False,
        )
        return result_text
