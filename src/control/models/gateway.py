from __future__ import annotations
import asyncio
import os
import time
import logging
from typing import Dict, Any, List
from openai import AsyncOpenAI
from src.control.models.model_router import get_model

logger = logging.getLogger(__name__)

class ModelGateway:
    """
    Tüm LLM çağrılarını yöneten merkezi ağ geçidi.
    Özellikler:
      - Multi-provider desteği (OpenRouter varsayılan)
      - Cost ve latency tracking
      - Fallback routing altyapısı
      - Task bazlı bütçe kontrolü
    """
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        self.request_timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "3"))
        self.max_retry_wait = int(os.getenv("LLM_MAX_RETRY_WAIT_SECONDS", "10"))
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            }
        )
        self._stats: Dict[str, Any] = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
            "per_model_stats": {}
        }

    async def chat_completion(
        self,
        task: str,
        messages: List[Dict[str, str]],
        **kwargs
    ):
        model = get_model(task)
        if not model:
            raise ValueError(f"Task '{task}' için model tanımlı değil veya yerel (local) bir işlem.")

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        **kwargs,
                    ),
                    timeout=self.request_timeout,
                )

                latency = int((time.monotonic() - t0) * 1000)
                tokens = response.usage.total_tokens if response.usage else 0

                # İstatistikleri güncelle
                self._update_stats(model, latency, tokens)
                return response

            except asyncio.TimeoutError as exc:
                last_error = RuntimeError(f"OpenAI call timeout after {self.request_timeout}s")
                logger.warning(
                    "ModelGateway timeout (%s) deneme %d/%d",
                    model,
                    attempt,
                    self.max_retries,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ModelGateway geçici hatası (%s) deneme %d/%d: %s",
                    model,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                wait_seconds = min(2 ** attempt, self.max_retry_wait)
                await asyncio.sleep(wait_seconds)

        logger.error("ModelGateway hatası (%s): %s", model, last_error)
        raise last_error if last_error else RuntimeError("ModelGateway failed without details")

    def _update_stats(self, model: str, latency: int, tokens: int):
        self._stats["total_calls"] += 1
        self._stats["total_latency_ms"] += latency
        self._stats["total_tokens"] += tokens
        
        if model not in self._stats["per_model_stats"]:
            self._stats["per_model_stats"][model] = {"calls": 0, "tokens": 0, "avg_latency": 0}
            
        ms = self._stats["per_model_stats"][model]
        ms["calls"] += 1
        ms["tokens"] += tokens
        # Hareketli ortalama latency
        ms["avg_latency"] = (ms["avg_latency"] * (ms["calls"] - 1) + latency) / ms["calls"]

    def get_stats(self) -> Dict[str, Any]:
        return self._stats
