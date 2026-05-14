from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

from openai import AsyncOpenAI

from src.control.models.model_router import get_model
from src.shared.config import config

logger = logging.getLogger(__name__)


class ModelGateway:
    """Tüm LLM çağrılarını merkezi olarak yöneten ağ geçidi."""

    def __init__(self):
        self.api_key = config.openai_api_key
        self.base_url = config.llm_base_url
        self.request_timeout = config.llm_timeout_seconds
        self.max_retries = config.llm_max_retries
        self.max_retry_wait = config.llm_max_retry_wait_seconds
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            },
        )
        self._stats: Dict[str, Any] = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
            "per_model_stats": {},
        }

    async def chat_completion(self, task: str, messages: List[Dict[str, str]], **kwargs):
        model = get_model(task)
        if not model:
            raise ValueError(f"Task '{task}' için model tanımlı değil veya yerel (local) bir işlem.")
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(model=model, messages=messages, **kwargs),
                    timeout=self.request_timeout,
                )
                latency = int((time.monotonic() - t0) * 1000)
                tokens = response.usage.total_tokens if response.usage else 0
                self._update_stats(model, latency, tokens)
                return response
            except Exception as exc:
                last_error = exc
                logger.warning("ModelGateway geçici hatası (%s) deneme %d/%d: %s", model, attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2 ** attempt, self.max_retry_wait))
        raise last_error if last_error else RuntimeError("ModelGateway failed without details")

    def _update_stats(self, model: str, latency: int, tokens: int):
        self._stats["total_calls"] += 1
        self._stats["total_latency_ms"] += latency
        self._stats["total_tokens"] += tokens
        if model not in self._stats["per_model_stats"]:
            self._stats["per_model_stats"][model] = {"calls": 0, "tokens": 0, "avg_latency": 0}
        stats = self._stats["per_model_stats"][model]
        stats["calls"] += 1
        stats["tokens"] += tokens
        stats["avg_latency"] = (stats["avg_latency"] * (stats["calls"] - 1) + latency) / stats["calls"]

    def get_stats(self) -> Dict[str, Any]:
        return self._stats
