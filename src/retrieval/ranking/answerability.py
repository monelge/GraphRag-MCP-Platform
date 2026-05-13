"""
Answerability Layer — Yetersiz context ile LLM çağrısı yapmayı önler.

Refactor değişiklikleri:
  - top1_score < 0.30 → INSUFFICIENT (önceki gibi)
  - total_chars < 200 → INSUFFICIENT (önceki gibi)
  - unique_sources < 2 AND top1_score < 0.55 → WEAK (önceki gibi)
  - YENİ: rerank_score < 0.15 → düşük yerel alaka sinyali → WEAK
  - YENİ: context_precision skoru (retrieval / top1 oranı)
  - YENİ: answerability_failure metrik döner (Postgres log için)
  - YENİ: diversity-aware — top5 aynı dosyadan geliyorsa weak (broad/architecture sorguları)

Güçlendirilmiş heuristikler:
  - Tek kaynak bile olsa top1_score >= 0.55 ise ANSWERABLE (strict değil)
  - Çok kaynak ama hepsi düşük skor → WEAK (yayılmış ama zayıf)
  - Diversity cezası yalnızca broad_summary/architecture sorgularında uygulanır
    (config_lookup/factual_doc gibi single-file sorguları cezalandırılmaz)
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass

# Diversity kontrolünün uygulandığı sorgu tipleri (broad/multi-file)
_DIVERSITY_CHECKED_TYPES = {"broad_summary", "architecture_analysis", "code_relation"}
# Bu eşiğin altında source_diversity → WEAK (broad sorgu için)
_MIN_DIVERSITY_THRESHOLD = 0.4


class Confidence(Enum):
    ANSWERABLE   = "answerable"
    WEAK         = "weak"
    INSUFFICIENT = "insufficient"


@dataclass
class AnswerabilityResult:
    confidence: Confidence
    reason: str
    top1_score: float
    unique_sources: int
    total_chars: int
    # Yeni metrikler
    avg_score: float = 0.0
    context_precision: float = 0.0   # top1_score / avg_score oranı (konsistans)
    source_diversity: float = 0.0    # unique_file_count / chunk_count
    is_failure: bool = False          # INSUFFICIENT → Postgres'e failure loglanır


def assess(chunks: list[dict], query_type: str = "factual_doc") -> AnswerabilityResult:
    """
    Chunk setini değerlendirerek LLM'e gidip gitmeyeceğine karar verir.
    final_score varsa onu, yoksa ham score'u kullanır.

    query_type: diversity kontrolü hangi sorgu tiplerinde aktif olacağını belirler.
    """
    if not chunks:
        return AnswerabilityResult(
            confidence=Confidence.INSUFFICIENT,
            reason="Hiç chunk döndürülmedi.",
            top1_score=0.0, unique_sources=0, total_chars=0, is_failure=True,
        )

    # Score seçimi: final_score öncelikli
    def _score(c):
        return float(c.get("final_score") or c.get("score") or 0.0)

    scores = [_score(c) for c in chunks]
    top1_score = scores[0]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # Context precision: top1'in ortalamasına oranı — 1.0 en iyi
    context_precision = (top1_score / avg_score) if avg_score > 0 else 0.0

    unique_files = {
        c.get("relative_path") or c.get("file", str(i))
        for i, c in enumerate(chunks)
    }
    unique_sources = len(unique_files)
    total_chars = sum(
        len(c.get("content") or c.get("code") or "")
        for c in chunks
    )

    # Diversity: benzersiz dosya sayısı / toplam chunk sayısı
    source_diversity = unique_sources / max(len(chunks), 1)

    # ── INSUFFICIENT kontrolleri ─────────────────────────────────────────────
    if top1_score < 0.30:
        return AnswerabilityResult(
            confidence=Confidence.INSUFFICIENT,
            reason=f"Top-1 skoru çok düşük ({top1_score:.2f} < 0.30). İlgili kaynak bulunamadı.",
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
            is_failure=True,
        )

    if total_chars < 200:
        return AnswerabilityResult(
            confidence=Confidence.INSUFFICIENT,
            reason=f"Chunk içerikleri çok kısa ({total_chars} karakter). Bilgi yetersiz.",
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
            is_failure=True,
        )

    # ── WEAK kontrolleri ─────────────────────────────────────────────────────
    # Rerank sonrası düşük yerel alaka — sadece rerank_score varsa değerlendir
    top1_rerank = float(chunks[0].get("rerank_score", 1.0))
    if top1_rerank < 0.15:
        return AnswerabilityResult(
            confidence=Confidence.WEAK,
            reason=f"Yerel rerank skoru düşük ({top1_rerank:.2f}). Yanıt kısmi olabilir.",
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
        )

    # Diversity kontrolü — yalnızca broad/architecture sorgularında
    if query_type in _DIVERSITY_CHECKED_TYPES and source_diversity < _MIN_DIVERSITY_THRESHOLD:
        return AnswerabilityResult(
            confidence=Confidence.WEAK,
            reason=(
                f"Düşük kaynak çeşitliliği ({source_diversity:.2f} < {_MIN_DIVERSITY_THRESHOLD}): "
                f"top-{len(chunks)} chunk büyük ölçüde aynı dosyalardan geliyor. "
                "Broad sorgu için daha geniş kapsam gerekebilir."
            ),
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
        )

    if unique_sources < 2 and top1_score < 0.55:
        return AnswerabilityResult(
            confidence=Confidence.WEAK,
            reason=f"Tek kaynak ve orta güven ({top1_score:.2f}). Yanıt kısmi olabilir.",
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
        )

    # Ortalama skor çok düşük (yayılmış ama zayıf retrieval)
    if avg_score < 0.20 and unique_sources >= 2:
        return AnswerabilityResult(
            confidence=Confidence.WEAK,
            reason=f"Ortalama skor düşük ({avg_score:.2f}). Çok kaynaklı ama güven zayıf.",
            top1_score=top1_score, unique_sources=unique_sources,
            total_chars=total_chars, avg_score=avg_score,
            context_precision=context_precision, source_diversity=source_diversity,
        )

    return AnswerabilityResult(
        confidence=Confidence.ANSWERABLE,
        reason="Retrieval sonuçları yeterli.",
        top1_score=top1_score, unique_sources=unique_sources,
        total_chars=total_chars, avg_score=avg_score,
        context_precision=context_precision, source_diversity=source_diversity,
    )
