"""
Redis tabanlı embedding + retrieval cache ve concurrency lock yönetimi.

Neden iki ayrı TTL?
- Embedding cache (24h): Aynı metin tekrar gelirse OpenRouter API çağrısından kaçınmak için.
  Embedding modeli değişmediği sürece aynı metin aynı vektörü üretir.
- Retrieval cache (2h): Arama sonuçları index değişince stale olur; kısa TTL ile otomatik expire.

Redis yoksa veya bağlantı hatalıysa tüm metodlar sessizce no-op döner;
hiçbir zaman exception fırlatmaz — cache her zaman "nice to have" katmanıdır.
"""

import hashlib
import json
import os
from typing import Optional

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

# Embedding cache: model değişmediği sürece deterministik — 24 saat yeterli.
_EMB_TTL_SEC = 60 * 60 * 24
# Retrieval cache: index güncellenince stale olabilir — kısa tutulur.
_RET_TTL_SEC = 60 * 60 * 2
# Index lock: uzun süren re-index işlemi için üst sınır 5 dakika.
_LOCK_TTL_SEC = 60 * 5


class RedisStore:
    """
    Embedding ve retrieval sonuçları için async Redis cache.
    Ayrıca eş zamanlı index işlemlerini engellemek için SETNX lock sağlar.
    """

    def __init__(self, url: str | None = None):
        if not _REDIS_AVAILABLE:
            # redis paketi yüklü değilse tüm metodlar no-op çalışır.
            self._client = None
            return
        url = url or os.getenv("REDIS_URL", "redis://redis:6379")
        self._client = aioredis.from_url(url, decode_responses=True)

    @property
    def available(self) -> bool:
        return self._client is not None

    # ── Yardımcı key üreticiler ──────────────────────────────────────────────

    def _emb_key(self, text: str) -> str:
        # Metin hash'i → key çakışması önler, bellek tahmin edilebilir
        digest = hashlib.sha256(text.encode()).hexdigest()
        return f"emb:{digest}"

    def _ret_key(self, query_hash: str, collection: str) -> str:
        return f"ret:{collection}:{query_hash}"

    def _lock_key(self, collection: str, op: str) -> str:
        return f"indexing_lock:{collection}:{op}"

    # ── Embedding Cache ──────────────────────────────────────────────────────

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        if not self._client:
            return None
        try:
            val = await self._client.get(self._emb_key(text))
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_embedding(self, text: str, embedding: list[float]) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(
                self._emb_key(text), _EMB_TTL_SEC, json.dumps(embedding)
            )
        except Exception:
            pass  # Cache yazma hatası hiçbir zaman işlemi engellememeli

    # ── Retrieval Cache ──────────────────────────────────────────────────────

    async def get_retrieval(self, collection: str, query: str) -> Optional[list]:
        if not self._client:
            return None
        try:
            key = self._ret_key(
                hashlib.sha256(query.encode()).hexdigest(), collection
            )
            val = await self._client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_retrieval(self, collection: str, query: str, results: list) -> None:
        if not self._client:
            return
        try:
            key = self._ret_key(
                hashlib.sha256(query.encode()).hexdigest(), collection
            )
            await self._client.setex(key, _RET_TTL_SEC, json.dumps(results))
        except Exception:
            pass

    async def invalidate_retrieval(self, collection: str) -> int:
        """
        incremental_index veya index_agent_docs tamamlandığında çağrılır.
        İlgili koleksiyona ait tüm retrieval cache key'lerini siler.
        Neden? Yeni index'lenen chunk'lar artık eski cache sonuçlarını stale kılar.
        """
        if not self._client:
            return 0
        try:
            keys = []
            async for key in self._client.scan_iter(f"ret:{collection}:*"):
                keys.append(key)
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception:
            return 0

    # ── Concurrency Lock ─────────────────────────────────────────────────────

    async def acquire_lock(self, collection: str, op: str = "index") -> bool:
        """
        SETNX tabanlı dağıtık lock. True: kilit alındı, devam et.
        False: başka bir index işlemi zaten devam ediyor, atla.

        Neden önemli? Aynı koleksiyon için eş zamanlı iki index_agent_docs çağrısı
        Qdrant'a duplikasyon veya tombstone çakışmasına yol açabilir.
        """
        if not self._client:
            # Redis yoksa kilitlenmeden devam et
            return True
        try:
            result = await self._client.set(
                self._lock_key(collection, op),
                "1",
                nx=True,   # sadece anahtar yoksa yaz
                ex=_LOCK_TTL_SEC,
            )
            return result is not None
        except Exception:
            return True  # Hata durumunda devam et — lock "nice to have"

    async def release_lock(self, collection: str, op: str = "index") -> None:
        if not self._client:
            return
        try:
            await self._client.delete(self._lock_key(collection, op))
        except Exception:
            pass

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    # ── Generic Raw Cache ───────────────────────────────────────────────────

    async def get_raw(self, key: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception:
            return None

    async def set_raw(self, key: str, value: str, ttl: int | None = None) -> None:
        if not self._client:
            return
        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
        except Exception:
            pass

    # ── Semantic Query Cache ─────────────────────────────────────────────────
    # Exact-match cache (get_retrieval/set_retrieval) yanında semantik cache.
    # Embedding vektörünü key prefix'e ekleyerek yakın sorgular için cache hit sağlar.
    # Benzerlik kontrolü caller tarafında yapılır (bu sadece vektör saklar).

    async def get_query_embedding(self, collection: str, query: str) -> list[float] | None:
        """Daha önce aranmış sorgu vektörünü döner (semantic cache lookup için)."""
        if not self._client:
            return None
        try:
            key = f"qemb:{collection}:{hashlib.sha256(query.encode()).hexdigest()}"
            val = await self._client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_query_embedding(
        self, collection: str, query: str, embedding: list[float]
    ) -> None:
        """Sorgu vektörünü semantic cache'e yazar (TTL=2h, retrieval cache ile aynı)."""
        if not self._client:
            return
        try:
            key = f"qemb:{collection}:{hashlib.sha256(query.encode()).hexdigest()}"
            await self._client.setex(key, _RET_TTL_SEC, json.dumps(embedding))
        except Exception:
            pass

    async def find_similar_cached_query(
        self,
        collection: str,
        query_embedding: list[float],
        similarity_threshold: float = 0.92,
    ) -> str | None:
        """
        Redis'teki qemb:collection:* key'lerini tarayarak
        sorgu vektörüne benzer (cosine >= threshold) bir önceki sorgunun
        hash'ini döner. Bulunamazsa None.

        Not: n≤500 key için O(n) tarama kabul edilebilir.
        Büyük cache'ler için ayrı bir similarity index gerekir (şimdilik kapsam dışı).
        """
        if not self._client or not query_embedding:
            return None
        try:
            import math

            def cosine(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b))
                ma = math.sqrt(sum(x * x for x in a))
                mb = math.sqrt(sum(x * x for x in b))
                return dot / (ma * mb) if ma and mb else 0.0

            async for key in self._client.scan_iter(f"qemb:{collection}:*"):
                val = await self._client.get(key)
                if not val:
                    continue
                cached_emb = json.loads(val)
                if cosine(query_embedding, cached_emb) >= similarity_threshold:
                    # Key formatı: qemb:{collection}:{hash}
                    query_hash = key.split(":")[-1]
                    return query_hash
        except Exception:
            pass
        return None
