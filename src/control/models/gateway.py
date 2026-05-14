from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from openai import AsyncOpenAI

from src.control.models.model_router import get_model
from src.shared.config import config

if TYPE_CHECKING:
    from src.control.models.budgets import BudgetManager
    from src.storage.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


class ModelGateway:
    """Tüm LLM çağrılarını merkezi olarak yöneten ağ geçidi."""

    def __init__(self, postgres_store: Optional["PostgresStore"] = None):
        self.api_key = config.openai_api_key
        self.base_url = config.llm_base_url
        self.request_timeout = config.llm_timeout_seconds
        self.max_retries = config.llm_max_retries
        self.max_retry_wait = config.llm_max_retry_wait_seconds
        # Token loglarını DB'ye yazmak için opsiyonel store referansı.
        # server.py init sonrası set edilir (circular import önlemek için).
        self._pg: Optional["PostgresStore"] = postgres_store
        self._budget_manager: Optional["BudgetManager"] = None
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

    def set_postgres(self, pg: "PostgresStore") -> None:
        """Circular import olmadan lifespan sonrası store bağlar."""
        self._pg = pg

    def set_budget_manager(self, bm: "BudgetManager") -> None:
        """Görev bazlı token bütçesi denetleyicisini bağlar."""
        self._budget_manager = bm

    async def chat_completion(
        self,
        task: str,
        messages: List[Dict[str, str]],
        task_id: str = None,
        node_name: str = None,
        **kwargs,
    ):
        if self._budget_manager and task_id:
            total_used = self._stats.get("total_tokens", 0)
            self._budget_manager.check_task(task_id, total_used)

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
                usage = response.usage
                prompt_tokens     = usage.prompt_tokens     if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0
                total_tokens      = usage.total_tokens      if usage else 0
                self._update_stats(model, latency, total_tokens)
                # DB'ye async yaz — hata olursa sessizce geç
                if self._pg:
                    asyncio.ensure_future(
                        self._pg.log_llm_usage(
                            model=model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                            latency_ms=latency,
                            task_id=task_id,
                            node_name=node_name,
                        )
                    )
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
