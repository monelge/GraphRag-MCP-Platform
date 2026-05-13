"""
Semantic Deduplication — benzer chunk'ların tekrar context'e girmesini önler.

Kural:
  İki chunk arasındaki cosine benzerliği > SIMILARITY_THRESHOLD ise
  düşük skorlu chunk elenir.

Neden gerekli?
  HybridSearch aynı kod parçasının farklı pozisyonlardan gelen kopyalarını
  döndürebilir. Bunları tekrar context'e almak:
  - Token bütçesini israf eder.
  - LLM'de "anchoring bias" (ilk gördüğüne aşırı odaklanma) yaratır.

Cosine benzerliği TF-IDF vektörleri üzerinden yerel olarak hesaplanır;
ek embedding API çağrısı gerekmez.
"""

from __future__ import annotations
import math
import re
from collections import Counter

SIMILARITY_THRESHOLD = 0.92


def _tfidf_vector(text: str) -> dict[str, float]:
    """
    Basit TF vektörü — IDF normalizasyonu olmadan.
    Tek doküman karşılaştırması için TF yeterlidir.
    """
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {t: c / total for t, c in counts.items()}


def _cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    """İki sparse vektörün cosine benzerliğini hesaplar."""
    shared = set(v1) & set(v2)
    if not shared:
        return 0.0
    dot = sum(v1[t] * v2[t] for t in shared)
    mag1 = math.sqrt(sum(x * x for x in v1.values()))
    mag2 = math.sqrt(sum(x * x for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


class SemanticDeduplicator:
    """
    Chunk listesinden semantik tekrarları eler.
    Giriş listesi relevance skoruna göre azalan sıralı olmalıdır.
    """

    def deduplicate(self, chunks: list[dict]) -> list[dict]:
        """
        Benzer chunk'lardan yüksek skorluyu tutar, düşük skorluyu atar.
        O(n²) ama n≤20 olduğu için pratik maliyet ihmal edilebilir.
        """
        if len(chunks) <= 1:
            return chunks

        # Her chunk için içerik vektörü oluştur
        vectors = []
        for c in chunks:
            text = c.get("code") or c.get("content") or ""
            vectors.append(_tfidf_vector(text))

        kept = []
        eliminated = set()

        for i, chunk in enumerate(chunks):
            if i in eliminated:
                continue
            kept.append(chunk)
            # Sonraki chunk'larla karşılaştır
            for j in range(i + 1, len(chunks)):
                if j in eliminated:
                    continue
                sim = _cosine(vectors[i], vectors[j])
                if sim > SIMILARITY_THRESHOLD:
                    # Düşük skorlu j'yi ele — i zaten daha yüksek sırada
                    eliminated.add(j)

        return kept
