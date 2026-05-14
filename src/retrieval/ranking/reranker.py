"""
CrossEncoder Reranker — HybridSearch top-20 sonrasında irrelevant chunk'ları eler.

Neden local reranker?
  - Her rerank için LLM çağrısı yapmak p95 latency hedefini (400ms) aşar.
  - fastembed 0.8.x cross-encoder modülü içermediğinden lightweight
    keyword-density + semantic-overlap skoru proxy olarak kullanılır.
  - Model routing kuralı: rerank = local işlem.

Skorlama formülü (ağırlıklı):
  rerank_score = keyword_density * 0.50 + token_overlap * 0.30 + name_bonus * 0.20

  keyword_density : query token'larının chunk içeriğinde görünme oranı
  token_overlap   : bi-gram örtüşme (phrase proximity)
  name_bonus      : chunk adı query'deki kelime içeriyorsa bonus
"""

from __future__ import annotations
import re

from src.retrieval.ranking.scorer import ScoreNormalizer


def _tokenize(text: str) -> list[str]:
    """Metni küçük harfe çevirip alfanümerik token'lara böler."""
    return re.findall(r"[a-z0-9_]+", text.lower())


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return {(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)}


def _rerank_score(query: str, chunk: dict) -> float:
    """
    Tek bir chunk için yerel rerank skoru hesaplar.
    0.0–1.0 aralığında normalize edilmiş skor döner.
    """
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return 0.0

    content = chunk.get("code") or chunk.get("content") or ""
    c_tokens = _tokenize(content)
    c_token_set = set(c_tokens)

    # 1. Keyword density: query token'larından kaçı content'te var?
    hits = sum(1 for t in q_tokens if t in c_token_set)
    keyword_density = hits / len(q_tokens)

    # 2. Bi-gram overlap: phrase düzeyinde yakınlık
    q_bg = _bigrams(list(_tokenize(query)))
    c_bg = _bigrams(c_tokens)
    if q_bg:
        bg_overlap = len(q_bg & c_bg) / len(q_bg)
    else:
        bg_overlap = 0.0

    # 3. Name bonus: fonksiyon/sınıf adı query terimleri içeriyorsa +bonus
    name = (chunk.get("name") or "").lower()
    name_tokens = set(_tokenize(name))
    name_bonus = min(1.0, len(name_tokens & q_tokens) / max(len(q_tokens), 1))

    return keyword_density * 0.50 + bg_overlap * 0.30 + name_bonus * 0.20


class LocalReranker:
    """
    HybridSearch sonuçlarını yerel skor ile yeniden sıralar.
    Hiçbir ağ çağrısı yapmaz — sıfır latency overhead.
    """

    def rerank(self, query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
        """
        chunk listesini rerank_score ekleyerek sıralar ve top_n döner.
        Her chunk'a 'rerank_score' anahtarı eklenir.
        """
        if not chunks:
            return []

        scored = []
        for chunk in chunks:
            r_score = _rerank_score(query, chunk)
            enriched = {**chunk, "rerank_score": round(r_score, 4)}
            scored.append(enriched)

        # Rerank skoruna göre azalan sırala; eşitlik durumunda retrieval skoru ikincil kriter
        scored.sort(
            key=lambda c: (c["rerank_score"], c.get("score", 0.0)),
            reverse=True,
        )
        results = scored[:top_n]
        normalizer = ScoreNormalizer()
        results = normalizer.normalize(results, strategy="minmax")
        return results
