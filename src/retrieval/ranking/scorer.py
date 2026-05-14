from __future__ import annotations

"""Skor normalizasyonu ve liste harmanlama yardımcıları."""

from typing import Any


class ScoreNormalizer:
    """Reranker'dan bağımsız skor ölçekleme ve birleştirme işlemlerini yapar."""

    @staticmethod
    def normalize(hits: list[dict], strategy: str = "minmax") -> list[dict]:
        """Hit skorlarını 0-1 aralığına çeker."""
        if not hits:
            return []

        if strategy != "minmax":
            raise ValueError(f"Desteklenmeyen normalize stratejisi: {strategy}")

        scores = [float(hit.get("score", 0.0) or 0.0) for hit in hits]
        min_score = min(scores)
        max_score = max(scores)
        if max_score == min_score:
            normalized_score = 1.0 if max_score > 0 else 0.0
            return [{**hit, "score": normalized_score} for hit in hits]

        scale = max_score - min_score
        return [
            {**hit, "score": round((float(hit.get("score", 0.0) or 0.0) - min_score) / scale, 6)}
            for hit in hits
        ]

    @classmethod
    def blend(
        cls,
        hits_a: list[dict],
        hits_b: list[dict],
        weight_a: float = 0.6,
    ) -> list[dict]:
        """İki hit listesini normalize edip ağırlıklı şekilde tek listede birleştirir."""
        safe_weight_a = min(max(weight_a, 0.0), 1.0)
        weight_b = 1.0 - safe_weight_a
        normalized_a = cls.normalize(hits_a)
        normalized_b = cls.normalize(hits_b)

        merged: dict[str, dict[str, Any]] = {}
        weighted_hits = [
            *((hit, safe_weight_a) for hit in normalized_a),
            *((hit, weight_b) for hit in normalized_b),
        ]
        for hit, weight in weighted_hits:
            dedup_key = cls._dedup_key(hit)
            blended_score = round(float(hit.get("score", 0.0) or 0.0) * weight, 6)
            existing = merged.get(dedup_key)
            if existing is None:
                merged[dedup_key] = {**hit, "score": blended_score}
                continue
            existing_score = round(float(existing.get("score", 0.0) or 0.0) + blended_score, 6)
            replacement = {**existing, "score": existing_score}
            if len(str(hit.get("code") or hit.get("content") or "")) > len(str(existing.get("code") or existing.get("content") or "")):
                replacement = {**existing, **hit, "score": existing_score}
            merged[dedup_key] = replacement

        return sorted(merged.values(), key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)

    @staticmethod
    def _dedup_key(hit: dict) -> str:
        payload = hit.get("payload") or {}
        parts = [
            str(hit.get("chunk_id") or payload.get("chunk_id") or ""),
            str(hit.get("file") or payload.get("file_path") or hit.get("relative_path") or ""),
            str(hit.get("name") or payload.get("name") or hit.get("title") or ""),
            str(hit.get("lines") or ""),
        ]
        if any(parts):
            return "|".join(parts)
        return "|".join(f"{key}={value}" for key, value in sorted((str(k), str(v)) for k, v in hit.items()))
