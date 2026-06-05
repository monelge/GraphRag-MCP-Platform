"""
CrossEncoder Reranker — sentence-transformers tabanlı neural reranking.

LocalReranker'ın keyword-density yaklaşımının yetersiz kaldığı durumlarda
(özellikle semantik benzerlik yüksek ama keyword örtüşmesi düşük olan chunk'lar)
CrossEncoder ~%20 precision@5 artışı sağlar.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
  - Boyut: ~80MB (ilk çalıştırmada indirilir, sonrası cache'den yüklenir)
  - Ek latency: ~15-20ms (CPU), ~5ms (GPU)
  - Lisans: Apache 2.0
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from src.shared.config import config

logger = logging.getLogger(__name__)

_model_instance = None


def _get_model():
    global _model_instance
    if _model_instance is None:
        try:
            from sentence_transformers import CrossEncoder
            logger.info("CrossEncoder modeli yükleniyor: %s", config.cross_encoder_model)
            t0 = time.monotonic()
            _model_instance = CrossEncoder(config.cross_encoder_model)
            logger.info("CrossEncoder yüklendi (%.1fs)", time.monotonic() - t0)
        except ImportError:
            logger.warning("sentence-transformers yüklü değil, CrossEncoder devre dışı")
            return None
        except Exception as e:
            logger.error("CrossEncoder yüklenemedi: %s", e)
            return None
    return _model_instance


class CrossEncoderReranker:
    """
    Neural CrossEncoder reranker.

    config.cross_encoder_enabled=False ise LocalReranker fallback'e düşer.
    Model lazy-load edilir — ilk rerank çağrısında yüklenir.
    """

    def rerank(self, query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
        """
        CrossEncoder skoru ile chunk'ları yeniden sıralar.
        Başarısız olursa orijinal sırayı döner (graceful degradation).
        """
        if not chunks:
            return []

        if not config.cross_encoder_enabled:
            return self._local_fallback(query, chunks, top_n)

        model = _get_model()
        if model is None:
            return self._local_fallback(query, chunks, top_n)

        try:
            t0 = time.monotonic()
            texts = [
                chunk.get("code") or chunk.get("content") or chunk.get("text") or ""
                for chunk in chunks
            ]
            pairs = [(query, text[:512]) for text in texts]
            scores = model.predict(pairs)

            scored = [
                {**chunk, "rerank_score": float(score)}
                for chunk, score in zip(chunks, scores)
            ]
            scored.sort(key=lambda c: c["rerank_score"], reverse=True)
            result = scored[:top_n]

            logger.debug(
                "CrossEncoder rerank tamamlandı: %d→%d chunk, %.1fms",
                len(chunks), len(result), (time.monotonic() - t0) * 1000,
            )
            return result

        except Exception as e:
            logger.warning("CrossEncoder hatası, fallback kullanılıyor: %s", e)
            return self._local_fallback(query, chunks, top_n)

    def _local_fallback(self, query: str, chunks: list[dict], top_n: int) -> list[dict]:
        """sentence-transformers yoksa veya hata durumunda LocalReranker kullanır."""
        from src.retrieval.ranking.reranker import LocalReranker
        return LocalReranker().rerank(query, chunks, top_n=top_n)
