from __future__ import annotations

"""Görev ve günlük bütçeleri process belleğinde izleyen basit yönetici."""

from dataclasses import dataclass
from threading import Lock
from src.shared.config import config


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


class BudgetExceededError(RuntimeError):
    """Görev veya günlük bütçe aşıldığında fırlatılır."""


class BudgetManager:
    """Config tabanlı limitleri okuyup in-memory sayaçlarla doğrular."""

    def __init__(self, task_budget: TaskBudget | None = None, daily_budget: DailyBudget | None = None):
        self.task_budget = task_budget or TaskBudget(
            max_tokens=config.budget_task_max_tokens,
            max_llm_calls=config.budget_task_max_llm_calls,
        )
        self.daily_budget = daily_budget or DailyBudget(
            max_cost_usd=config.budget_daily_max_usd,
            max_tokens=config.budget_daily_max_tokens,
        )
        self._task_usage: dict[str, dict[str, int]] = {}
        self._daily_usage = {"tokens": 0, "cost_usd": 0.0}
        self._lock = Lock()
        # V2: Verim denetimi için ardışık başarısızlıkları izle
        self._consecutive_failures: dict[str, int] = {}

    def check_task(self, task_id: str, tokens_used: int, last_success: bool = True) -> bool:
        """Görev bazlı bütçe ve verim (yield) denetimi."""
        key = task_id or "default"
        with self._lock:
            # 1. Bütçe Sayaçlarını Güncelle
            current = self._task_usage.setdefault(key, {"tokens": 0, "llm_calls": 0})
            next_tokens = current["tokens"] + max(tokens_used, 0)
            next_calls = current["llm_calls"] + 1

            # 2. Hard Limits (Bütçe)
            if next_tokens > self.task_budget.max_tokens:
                raise BudgetExceededError(f"Task token bütçesi aşıldı: {task_id}")
            if next_calls > self.task_budget.max_llm_calls:
                raise BudgetExceededError(f"Task LLM çağrı bütçesi aşıldı: {task_id}")

            # 3. Control Plane V2: Yield Analysis (Verim Denetimi)
            # Eğer ajan ardışık olarak hata alıyorsa, bütçe dolmadan durdur
            fail_count = self._consecutive_failures.get(key, 0)
            if not last_success:
                fail_count += 1
                self._consecutive_failures[key] = fail_count
                if fail_count >= 2:
                    raise BudgetExceededError(f"⚠️ Runaway Loop Tespit Edildi: Task {task_id} ardışık 2 kez başarısız oldu. İşlem maliyet verimliliği için durduruldu.")
            else:
                self._consecutive_failures[key] = 0 # Başarı gelirse sayacı sıfırla

            current["tokens"] = next_tokens
            current["llm_calls"] = next_calls
            return True

    def check_daily(self, tokens_used: int, cost_usd: float) -> bool:
        """Günlük toplam tüketimin env ile tanımlanan limitler içinde kalmasını sağlar."""
        with self._lock:
            next_tokens = self._daily_usage["tokens"] + max(tokens_used, 0)
            next_cost = self._daily_usage["cost_usd"] + max(cost_usd, 0.0)
            if next_tokens > self.daily_budget.max_tokens:
                raise BudgetExceededError("Günlük token bütçesi aşıldı")
            if next_cost > self.daily_budget.max_cost_usd:
                raise BudgetExceededError("Günlük maliyet bütçesi aşıldı")
            self._daily_usage["tokens"] = next_tokens
            self._daily_usage["cost_usd"] = next_cost
            return True
