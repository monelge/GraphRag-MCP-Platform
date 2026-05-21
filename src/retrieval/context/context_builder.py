"""
ContextBuilder — Yeni öncelik sistemi ile chunk seçimi.

Değişiklikler (refactor):
  1. final_score hesabı:
       final_score = retrieval_score*0.45 + rerank_score*0.30
                   + graph_centrality*0.15 + recency_score*0.10
  2. Chunk tip önceliği: Function > Method > Interface > Class > File > Module
  3. Tam dosya context'i yalnızca: architecture_analysis, broad_summary, dependency tracing
  4. Duplicate chunk içermez — SemanticDeduplicator ile birlikte çalışır.
  5. Düşük relevance chunk'ları otomatik elenir (MIN_SCORE eşiği).
"""

from __future__ import annotations
from src.shared.config import config

# Chunk tipi → öncelik puanı (yüksek = önce seç)
_TYPE_PRIORITY: dict[str, int] = {
    "function":  6,
    "method":    5,
    "interface": 4,
    "class":     3,
    "file":      2,
    "module":    1,
}

# Yalnızca bu query tiplerinde tam dosya/modül chunk'larına izin ver
_FULL_FILE_ALLOWED_TYPES = {"architecture_analysis", "broad_summary", "dependency_tracing"}


def compute_final_score(chunk: dict) -> float:
    """
    Ağırlıklı final skor hesaplar.
    Eksik alanlar için güvenli varsayılanlar kullanılır.
    """
    retrieval   = float(chunk.get("score", 0.0))
    rerank      = float(chunk.get("rerank_score", retrieval * 0.6))   # yoksa retrieval'ın %60'ı
    centrality  = float(chunk.get("graph_centrality", 0.0))
    recency     = float(chunk.get("recency_score", 0.5))              # bilinmiyorsa orta değer

    # Tip bonusu: Function/Method chunk'larına hafif avantaj (0–0.05)
    chunk_type  = (chunk.get("type") or chunk.get("chunk_type") or "").lower()
    type_bonus  = _TYPE_PRIORITY.get(chunk_type, 0) / 100.0

    w = config.context_score_weights
    raw = (
        retrieval    * w["retrieval"]
        + rerank     * w["rerank"]
        + centrality * w["centrality"]
        + recency    * w["recency"]
        + type_bonus
    )
    return round(min(raw, 1.0), 4)


class ContextBuilder:
    """
    Chunk listesini token budget ve final_score'a göre seçer.
    Dışarıdan sadece `build()` metodu kullanılır.
    """

    def __init__(self, token_budget: int | None = None, query_type: str = "factual_doc"):
        self._budget = (token_budget or config.default_token_budget) * config.context_chars_per_token
        self._query_type = query_type

    def build(self, chunks: list[dict]) -> list[dict]:
        """
        1. Her chunk'a final_score hesapla.
        2. Tam dosya chunk'larını sadece izin verilen query tiplerinde dahil et.
        3. MIN_SCORE altındakileri ele.
        4. final_score'a göre sırala, token bütçesine sığdır.
        """
        if not chunks:
            return []

        # 1. final_score ekle
        enriched = []
        for c in chunks:
            fs = compute_final_score(c)
            enriched.append({**c, "final_score": fs})

        # 2. Tam dosya/modül chunk'larını filtrele (izin verilmiyorsa)
        if self._query_type not in _FULL_FILE_ALLOWED_TYPES:
            enriched = [
                c for c in enriched
                if (c.get("type") or c.get("chunk_type") or "").lower()
                not in ("file", "module")
            ]
            # Filtre sonrası boş kaldıysa orijinal listeye geri dön
            if not enriched:
                enriched = [{**c, "final_score": compute_final_score(c)} for c in chunks]

        # 3. MIN_SCORE filtresi
        above_threshold = [c for c in enriched if c["final_score"] >= config.min_final_score]
        if not above_threshold:
            above_threshold = enriched  # Hepsi düşükse yine de top1'i ver

        # 4. final_score azalan sırala
        above_threshold.sort(key=lambda c: c["final_score"], reverse=True)

        # 5. Token bütçesine göre seç
        selected: list[dict] = []
        used_chars = 0
        seen_ids: set[str] = set()

        for chunk in above_threshold:
            if len(selected) >= config.max_context_chunks:
                break

            chunk_id = chunk.get("chunk_id") or id(chunk)
            if chunk_id in seen_ids:
                continue

            content = chunk.get("code") or chunk.get("content") or ""
            if used_chars + len(content) > self._budget and selected:
                break

            selected.append(chunk)
            seen_ids.add(chunk_id)
            used_chars += len(content)

        # top1 garantisi
        if not selected and above_threshold:
            selected = [above_threshold[0]]

        return selected

    @staticmethod
    def _source_key(chunk: dict) -> str:
        path = chunk.get("relative_path") or chunk.get("file", "")
        h1 = chunk.get("h1", "")
        return f"{path}::{h1}"
