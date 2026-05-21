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

    async def _embed_one(self, text: str, retries: int = 3) -> list[float]:
        text = text[:_MAX_CHARS].strip()

        if len(text) < 10:
            return [0.0] * config.embedding_dim

        for attempt in range(retries):
            try:
                response = await self.client.embeddings.create(
                    model=self.model, input=text
                )
                if not response or not response.data:
                    return [0.0] * config.embedding_dim
                return response.data[0].embedding
            except (ValueError, TypeError) as e:
                if attempt == 0:
                    text = text[:len(text) // 2]
                    continue
                return [0.0] * config.embedding_dim
            except Exception as e:
                err = str(e)
                if "rate" in err.lower() or "429" in err:
                    await asyncio.sleep(2 ** attempt)
                elif attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    return [0.0] * config.embedding_dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Metinleri vektörlere çevirir."""
        results = []
        for text in texts:
            # 1. Cache kontrolü
            cached = None
            if self._redis and hasattr(self._redis, "get_embedding"):
                cached = await self._redis.get_embedding(text)
            
            if cached is not None:
                results.append(cached)
                continue

            # 2. API çağrısı
            emb = await self._embed_one(text)

            # 3. Cache'e yaz
            if self._redis and hasattr(self._redis, "set_embedding"):
                await self._redis.set_embedding(text, emb)

            results.append(emb)
        return results
