"""
Token Budget Optimizer — context boyutunu query tipine göre dinamik kısıtlar.

Neden sabit budget değil?
  - config_lookup: tek bir komut/ayar beklenir → 1200 token yeterli
  - factual_doc: kural/tanım açıklaması → 1800 token
  - code_relation: bağımlılık zinciri → 2500 token
  - broad_summary: genel bakış → 4000 token (maksimum)

"128k context brute force" yaklaşımının tam tersi:
  LLM'e daha az ama daha isabetli chunk gönder.

Token tahmini: 1 token ≈ 4 karakter (İngilizce/kod için güvenli sabit).
"""

from __future__ import annotations
from src.retrieval.search.query_classifier import QueryType

# Query tipi → maksimum token bütçesi
TOKEN_BUDGET: dict[str, int] = {
    "config_lookup":  1200,
    "factual_doc":    1800,
    "code_relation":  2500,
    "broad_summary":  4000,
}

_CHARS_PER_TOKEN = 4


def get_budget_chars(query_type: str) -> int:
    """Query tipine göre karakter cinsinden token bütçesi döner."""
    tokens = TOKEN_BUDGET.get(query_type, 1800)
    return tokens * _CHARS_PER_TOKEN


class TokenBudgetOptimizer:
    """
    Chunk listesini query tipine özgü token bütçesiyle kırpar.
    final_score üzerinden sıralı listede bütçe dolana kadar chunk alır.
    """

    def optimize(
        self,
        chunks: list[dict],
        query_type: str,
        score_key: str = "final_score",
    ) -> list[dict]:
        """
        Bütçeye sığan en yüksek skorlu chunk'ları seçer.
        score_key: hangi skor alanına göre sıralanacağı (final_score | score | rerank_score)
        """
        if not chunks:
            return []

        budget_chars = get_budget_chars(query_type)

        # Önce skora göre sırala (azalan)
        sorted_chunks = sorted(
            chunks,
            key=lambda c: c.get(score_key, c.get("score", 0.0)),
            reverse=True,
        )

        selected: list[dict] = []
        used_chars = 0

        for chunk in sorted_chunks:
            content = chunk.get("code") or chunk.get("content") or ""
            chunk_chars = len(content)

            if used_chars + chunk_chars > budget_chars:
                # Bütçe doldu — daha küçük bir sonraki chunk sığabilir mi?
                # (greedy değil: ilk aşımda dur)
                break

            selected.append(chunk)
            used_chars += chunk_chars

        # En az 1 chunk her zaman döner (top1 garantisi)
        if not selected and sorted_chunks:
            selected = [sorted_chunks[0]]

        return selected
