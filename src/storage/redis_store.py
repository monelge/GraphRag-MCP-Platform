from __future__ import annotations
import hashlib
import json
import logging
import math
from typing import Optional
from redis.asyncio import Redis
from src.shared.config import config

logger = logging.getLogger(__name__)

class RedisStore:
    def __init__(self, url: Optional[str] = None):
        self.url = url or config.redis_url
        self._client: Optional[Redis] = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def connect(self):
        if self._client:
            return
        try:
            self._client = Redis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            self._available = True
            logger.info("Redis bağlantısı başarılı: %s", self.url)
        except Exception as exc:
            logger.warning("Redis bağlantısı kurulamadı (cache devre dışı): %s", exc)
            self._available = False
            self._client = None

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
            self._available = False

    # --- Cache Metodları ---

    async def get_retrieval(self, collection: str, query: str) -> Optional[list]:
        if not self.available: return None
        try:
            if query.startswith("__hash__:"):
                query_hash = query.replace("__hash__:", "")
            else:
                query_hash = hashlib.sha256(query.encode()).hexdigest()
            
            val = await self._client.get(f"ret:{collection}:{query_hash}")
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_retrieval(self, collection: str, query: str, results: list, ex: int = 3600):
        if not self.available: return
        try:
            if query.startswith("__hash__:"):
                query_hash = query.replace("__hash__:", "")
            else:
                query_hash = hashlib.sha256(query.encode()).hexdigest()
                
            await self._client.set(f"ret:{collection}:{query_hash}", json.dumps(results), ex=ex)
        except Exception:
            pass

    async def invalidate_retrieval(self, collection: str) -> int:
        """Koleksiyona ait tüm retrieval cache'ini temizler."""
        if not self.available: return 0
        try:
            keys = []
            async for key in self._client.scan_iter(f"ret:{collection}:*"):
                keys.append(key)
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception:
            return 0

    async def get_raw(self, key: str) -> Optional[str]:
        if not self.available: return None
        try:
            return await self._client.get(key)
        except Exception:
            return None

    async def set_raw(self, key: str, value: str, ttl: int = 3600):
        if not self.available: return
        try:
            await self._client.set(key, value, ex=ttl)
        except Exception:
            pass

    # --- Embedding Cache Metodları ---

    def _embedding_key(self, text: str) -> str:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"emb:{h}"

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        if not self.available: return None
        try:
            val = await self._client.get(self._embedding_key(text))
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_embedding(self, text: str, vector: list[float], ex: int = 86400):
        if not self.available: return
        try:
            await self._client.set(self._embedding_key(text), json.dumps(vector), ex=ex)
        except Exception:
            pass

    # --- Semantic Query Cache Metodları ---

    async def get_query_embedding(self, collection: str, query: str) -> list[float] | None:
        if not self.available: return None
        try:
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            key = f"qemb:{collection}:{query_hash}"
            val = await self._client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None

    async def set_query_embedding(self, collection: str, query: str, embedding: list[float], ex: int = 7200) -> None:
        if not self.available: return
        try:
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            key = f"qemb:{collection}:{query_hash}"
            await self._client.set(key, json.dumps(embedding), ex=ex)
        except Exception:
            pass

    async def find_similar_cached_query(
        self,
        collection: str,
        query_embedding: list[float],
        similarity_threshold: float = 0.92,
    ) -> str | None:
        if not self.available or not query_embedding:
            return None
        try:
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
                    return key.split(":")[-1]
        except Exception:
            pass
        return None

    # --- Lock / Semaphor Metodları ---

    async def acquire_lock(self, collection: str, op: str = "index", timeout: int = 600) -> bool:
        if not self.available: return True
        key = f"lock:{op}:{collection}"
        try:
            success = await self._client.set(key, "1", ex=timeout, nx=True)
            return bool(success)
        except Exception:
            return True

    async def release_lock(self, collection: str, op: str = "index"):
        if not self.available: return
        key = f"lock:{op}:{collection}"
        try:
            await self._client.delete(key)
        except Exception:
            pass
