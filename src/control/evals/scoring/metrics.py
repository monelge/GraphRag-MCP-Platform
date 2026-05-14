"""Retrieval eval metrikleri için yardımcı fonksiyonlar."""

from __future__ import annotations

from typing import Iterable, Sequence


def hit_at_k(retrieved: Sequence[str], expected: Sequence[str], k: int) -> float:
    """İlk k sonuç içinde beklenen dosyalardan biri varsa 1.0 döner."""
    top_items = retrieved[:k]
    return 1.0 if any(any(exp in item for exp in expected) for item in top_items) else 0.0


def mrr(retrieved: Sequence[str], expected: Sequence[str]) -> float:
    """İlk doğru sonucun reciprocal rank değerini döner."""
    for index, item in enumerate(retrieved, start=1):
        if any(exp in item for exp in expected):
            return 1.0 / index
    return 0.0


def faithfulness_score(answer: str, context: Iterable[str]) -> float:
    """Basit bir bağlam kapsama oranı ile faithfulness skoru üretir."""
    normalized_answer = (answer or "").lower()
    context_items = [item.lower() for item in context if item]
    if not normalized_answer or not context_items:
        return 0.0
    matches = sum(1 for item in context_items if item in normalized_answer)
    return min(1.0, matches / max(1, len(context_items)))
