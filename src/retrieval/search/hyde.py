"""
HyDE (Hypothetical Document Expansion) — Adaptif Query Expansion.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING
from src.shared.config import config

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Expansion başına maksimum aday (normal top20'nin yarısı)
_EXPAND_K = 10


async def expand_query(
    query: str,
    llm_client: "AsyncOpenAI",
    model: str,
) -> list[str]:
    """
    Verilen sorgu için ucuz LLM ile semantik expansion'lar üretir.
    """
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Verilen kod arama sorgusundan {config.hyde_expansion_count} farklı "
                        "teknik İngilizce arama terimi üret. "
                        "Her terim kod tabanında geçebilecek gerçek sembol, fonksiyon "
                        "veya kavram adı olmalı. "
                        f"Sadece {config.hyde_expansion_count} satır döndür, her satır bir terim. "
                        "Numara veya madde işareti kullanma."
                    ),
                },
                {"role": "user", "content": f"Sorgu: {query}"},
            ],
            max_tokens=120,
            temperature=0.3,
        )
        lines = resp.choices[0].message.content.strip().splitlines()
        # Boş satır ve çok uzun satırları filtrele
        expansions = [l.strip() for l in lines if 3 < len(l.strip()) < 120]
        return expansions[:config.hyde_expansion_count]
    except Exception as exc:
        logger.warning("HyDE expansion başarısız: %s", exc)
        return []


async def hyde_retrieve(
    query: str,
    expansions: list[str],
    searcher,                   # HybridSearcher instance
    query_filter,
    top_k: int,
) -> list[dict]:
    """
    Orijinal query + expansions için paralel retrieval yapar.
    Sonuçları RRF rank skoru ile birleştirir.
    """
    all_queries = [query] + expansions

    async def _fetch(q: str, weight: float) -> list[dict]:
        try:
            results = await searcher.search(
                q, top_k=_EXPAND_K, query_filter=query_filter
            )
            # Expansion kaynaklı chunk'ları işaretle (düşük ağırlık)
            for r in results:
                r["_expansion_weight"] = weight
            return results
        except Exception as exc:
            logger.warning("HyDE fetch hatası [%s]: %s", q, exc)
            return []

    try:
        async with asyncio.timeout(config.hyde_budget_seconds):
            # Orijinal query ağırlık 1.0, expansion'lar 0.7
            weights = [1.0] + [0.7] * len(expansions)
            batches = await asyncio.gather(*[
                _fetch(q, w) for q, w in zip(all_queries, weights)
            ])
    except TimeoutError:
        logger.warning("HyDE timeout (%.1fs), mevcut sonuçlarla devam.", config.hyde_budget_seconds)
        # Timeout'ta en az orijinal query sonucu olsun
        batches = [await _fetch(query, 1.0)]

    # Tüm chunk'ları birleştir — name/file bazında deduplicate
    seen: dict[str, dict] = {}
    for batch in batches:
        for chunk in batch:
            key = _chunk_key(chunk)
            if key not in seen:
                seen[key] = chunk
            else:
                # Aynı chunk tekrar geldi: skoru en yüksek olanı tut
                existing_score = float(seen[key].get("score", 0))
                new_score = float(chunk.get("score", 0)) * chunk.get("_expansion_weight", 1.0)
                if new_score > existing_score:
                    seen[key] = chunk

    merged = sorted(seen.values(), key=lambda c: float(c.get("score", 0)), reverse=True)
    return merged[:top_k * 2]    # reranker için yeterli aday bırak


def _chunk_key(chunk: dict) -> str:
    """Chunk için benzersiz key üretir."""
    name = chunk.get("name", "")
    file = chunk.get("file", "")
    lines = str(chunk.get("lines", ""))
    raw = f"{file}:{name}:{lines}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
