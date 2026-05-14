from __future__ import annotations

"""Görev ve günlük bütçeleri process belleğinde izleyen basit yönetici."""

import os
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class TaskBudget:
    """Tek görev için izin verilen üst sınırları tanımlar."""

    max_llm_calls: int = 20
    max_tokens: int = 50000


@dataclass(frozen=True)
class DailyBudget:
    """Günlük toplam tüketim limitlerini tanımlar."""

    max_cost_usd: float = 10.0
    max_tokens: int = 1_000_000


class BudgetManager:
    """Env tabanlı limitleri okuyup in-memory sayaçlarla doğrular."""

    def __init__(self, task_budget: TaskBudget | None = None, daily_budget: DailyBudget | None = None):
        self.task_budget = task_budget or TaskBudget(
            max_tokens=int(os.getenv("BUDGET_TASK_MAX_TOKENS", "50000")),
            max_llm_calls=int(os.getenv("BUDGET_TASK_MAX_LLM_CALLS", "20")),
        )
        self.daily_budget = daily_budget or DailyBudget(
            max_cost_usd=float(os.getenv("BUDGET_DAILY_MAX_USD", "10.0")),
            max_tokens=int(os.getenv("BUDGET_DAILY_MAX_TOKENS", "1000000")),
        )
        self._task_usage: dict[str, dict[str, int]] = {}
        self._daily_usage = {"tokens": 0, "cost_usd": 0.0}
        self._lock = Lock()

    def check_task(self, task_id: str, tokens_used: int) -> bool:
        """Görev bazlı token bütçesinin aşılmadığını doğrular."""
        key = task_id or "default"
        with self._lock:
            current = self._task_usage.setdefault(key, {"tokens": 0, "llm_calls": 0})
            next_tokens = current["tokens"] + max(tokens_used, 0)
            next_calls = current["llm_calls"] + 1
            if next_tokens > self.task_budget.max_tokens:
                return False
            if next_calls > self.task_budget.max_llm_calls:
                return False
            current["tokens"] = next_tokens
            current["llm_calls"] = next_calls
            return True

    def check_daily(self, tokens_used: int, cost_usd: float) -> bool:
        """Günlük toplam tüketimin env ile tanımlanan limitler içinde kalmasını sağlar."""
        with self._lock:
            next_tokens = self._daily_usage["tokens"] + max(tokens_used, 0)
            next_cost = self._daily_usage["cost_usd"] + max(cost_usd, 0.0)
            if next_tokens > self.daily_budget.max_tokens:
                return False
            if next_cost > self.daily_budget.max_cost_usd:
                return False
            self._daily_usage["tokens"] = next_tokens
            self._daily_usage["cost_usd"] = next_cost
            return True
