"""
HyDE (Hypothetical Document Expansion) — Adaptif Query Expansion.

Çalışma prensibi:
  Kullanıcı sorgusu semantik olarak belirsizse veya ilk retrieval zayıf
  döndüyse, ucuz bir LLM ile 3 alternatif query üretilir:
    "login neden düşüyor"
      → ["auth session invalidation", "refresh token expiry",
         "jwt expiration handler", "cookie rotation policy"]

  Her expansion için Qdrant'ta ayrı retrieval yapılır (asyncio.gather),
  sonuçlar birleştirilerek SemanticDeduplicator ile temizlenir.

Neden adaptif?
  - Her sorgu için HyDE çalıştırmak hem maliyetli hem de yavaş.
  - Sadece should_rewrite() True döndüğünde veya ilk retrieval recall'ı
    düşükse aktive et.

Maliyet koruması:
  - Expansion başına top_k değil, daha düşük expand_k kullanılır.
  - Global asyncio.timeout(HYDE_BUDGET_SECONDS) ile kısıtlanır.
  - Expansion LLM çağrısı cost guardrail'e dahil edilir (AUX LLM).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Expansion başına maksimum aday (normal top20'nin yarısı)
_EXPAND_K = 10
# HyDE toplam bütçesi (saniye) — timeout
_HYDE_BUDGET_SECONDS = float(os.getenv("HYDE_BUDGET_SECONDS", "8.0"))
# Üretilecek expansion sayısı
_EXPANSION_COUNT = int(os.getenv("HYDE_EXPANSION_COUNT", "3"))


async def expand_query(
    query: str,
    llm_client: "AsyncOpenAI",
    model: str,
) -> list[str]:
    """
    Verilen sorgu için ucuz LLM ile semantik expansion'lar üretir.
    Hata durumunda boş liste döner (orijinal query ile devam edilir).

    Cache'lenebilir: caller tarafından normalized query üzerinden key üretilmeli.
    """
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Verilen kod arama sorgusundan {_EXPANSION_COUNT} farklı "
                        "teknik İngilizce arama terimi üret. "
                        "Her terim kod tabanında geçebilecek gerçek sembol, fonksiyon "
                        "veya kavram adı olmalı. "
                        f"Sadece {_EXPANSION_COUNT} satır döndür, her satır bir terim. "
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
        return expansions[:_EXPANSION_COUNT]
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

    Timeout: HYDE_BUDGET_SECONDS içinde bitmezse mevcut sonuçlarla devam.
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
        async with asyncio.timeout(_HYDE_BUDGET_SECONDS):
            # Orijinal query ağırlık 1.0, expansion'lar 0.7
            weights = [1.0] + [0.7] * len(expansions)
            batches = await asyncio.gather(*[
                _fetch(q, w) for q, w in zip(all_queries, weights)
            ])
    except TimeoutError:
        logger.warning("HyDE timeout (%.1fs), mevcut sonuçlarla devam.", _HYDE_BUDGET_SECONDS)
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
