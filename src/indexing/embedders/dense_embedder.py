from openai import AsyncOpenAI
import asyncio
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.redis_store import RedisStore

# text-embedding-3-small maksimum token limiti ~8192; C# kodu için ~2.5 chr/token.
# Güvenli üst sınır: 20000 karakter ≈ 8000 token.
_MAX_CHARS = 20_000


class DenseEmbedder:
    """
    Neden dense (yoğun) vektör?
    "authenticate user" sorgusunu "login function" ile eşleştirmek için
    anlamsal yakınlığa ihtiyaç vardır — BM25 bunu yapamaz.

    OpenRouter, OpenAI istemci kütüphanesiyle tam uyumludur;
    sadece base_url ve api_key farklıdır.

    redis_store opsiyoneldir — verilirse embedding sonuçları 24h cache'lenir.
    Aynı metin ikinci kez geldiğinde API çağrısı yapılmaz.
    """

    def __init__(self, redis_store: "RedisStore | None" = None):
        # OpenRouter, OpenAI SDK'sının aynı HTTP arayüzünü kullanır.
        # base_url değiştirerek hiçbir kod değişikliği gerekmez.
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                # OpenRouter, hangi uygulamanın istek yaptığını loglamak için
                # bu başlıkları kullanır — zorunlu değil ama önerilir.
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            },
        )
        self.model = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
        # Redis cache: API maliyetini ve latency'yi düşürür
        self._redis = redis_store

    async def _embed_one(self, text: str, retries: int = 3) -> list[float]:
        # Token limitini aşan metinleri kırp; anlam taşıyan kısım genellikle başta olur.
        text = text[:_MAX_CHARS].strip()

        # Boş veya anlamsız kısa metin gelirse sıfır vektör döndür.
        # Neden hata fırlatmak yerine sıfır vektör? İndeksleme tüm batch'i durdurmasın;
        # bu chunk arama sonuçlarında zaten üste çıkmaz (skor=0).
        if len(text) < 10:
            return [0.0] * int(os.getenv("EMBEDDING_DIM", "1536"))

        for attempt in range(retries):
            try:
                response = await self.client.embeddings.create(
                    model=self.model, input=text
                )
                # Bazı OpenRouter yanıtlarında data listesi boş gelebilir
                if not response.data:
                    return [0.0] * int(os.getenv("EMBEDDING_DIM", "1536"))
                return response.data[0].embedding
            except ValueError as e:
                # "No embedding data received" — metni küçülterek bir kez daha dene
                if attempt == 0:
                    text = text[:len(text) // 2]
                    continue
                return [0.0] * int(os.getenv("EMBEDDING_DIM", "1536"))
            except Exception as e:
                err = str(e)
                if "rate" in err.lower() or "429" in err:
                    # Rate limit: üstel geri çekilme (1s, 2s, 4s)
                    await asyncio.sleep(2 ** attempt)
                elif attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    raise
        raise RuntimeError("embed_one başarısız oldu")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Metinleri vektörlere çevirir.
        1. Redis cache'e bak — hit varsa API çağrısı yapma.
        2. Cache miss → OpenRouter API'ye gönder.
        3. Sonucu cache'e yaz (TTL=24h).

        OpenRouter embedding API'si tek seferde 1 metin kabul eder.
        """
        results = []
        for text in texts:
            # 1. Cache kontrolü
            cached = await self._redis.get_embedding(text) if self._redis else None
            if cached is not None:
                results.append(cached)
                continue

            # 2. API çağrısı
            emb = await self._embed_one(text)

            # 3. Cache'e yaz
            if self._redis:
                await self._redis.set_embedding(text, emb)

            results.append(emb)
        return results
