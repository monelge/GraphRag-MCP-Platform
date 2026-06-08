from __future__ import annotations
from openai import AsyncOpenAI
import asyncio
from typing import TYPE_CHECKING
from src.shared.config import config

if TYPE_CHECKING:
    from src.storage.redis_store import RedisStore

# text-embedding-3-small maksimum token limiti ~8192; C# kodu için ~2.5 chr/token.
# Güvenli üst sınır: 20000 karakter ≈ 8000 token.
_MAX_CHARS = 20_000


class DenseEmbedder:
    """
    Metinleri yoğun (dense) vektörlere çevirir.
    Redis cache ile mükerrer çağrıları engeller.
    """

    def __init__(self, redis_store: "RedisStore | None" = None):
        self.client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.llm_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            },
        )
        self.model = config.embedding_model
        self._redis = redis_store

    async def _embed_bulk(self, texts: list[str], retries: int = 3) -> list[list[float]]:
        """Tek API çağrısında tüm batch'i gömer — 32 request yerine 1 request."""
        safe = [t[:_MAX_CHARS].strip() for t in texts]
        zero = [0.0] * config.embedding_dim

        for attempt in range(retries):
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=[t if len(t) >= 10 else "." for t in safe],
                )
                result = [zero] * len(safe)
                for item in response.data:
                    result[item.index] = item.embedding
                # Çok kısa metinleri sıfır vektör olarak işaretle
                for i, t in enumerate(safe):
                    if len(t) < 10:
                        result[i] = zero
                return result
            except Exception as e:
                err = str(e)
                if ("rate" in err.lower() or "429" in err) and attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                elif attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    return [zero] * len(texts)
        return [zero] * len(texts)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Cache kontrolü yapıp cache'siz metinleri tek API çağrısında gömer."""
        cached_results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []

        for i, text in enumerate(texts):
            if self._redis and hasattr(self._redis, "get_embedding"):
                cached = await self._redis.get_embedding(text)
                if cached is not None:
                    cached_results[i] = cached
                    continue
            uncached_indices.append(i)

        if uncached_indices:
            bulk_embeddings = await self._embed_bulk([texts[i] for i in uncached_indices])
            for idx, emb in zip(uncached_indices, bulk_embeddings):
                cached_results[idx] = emb
                if self._redis and hasattr(self._redis, "set_embedding"):
                    await self._redis.set_embedding(texts[idx], emb)

        return [r if r is not None else [0.0] * config.embedding_dim for r in cached_results]
