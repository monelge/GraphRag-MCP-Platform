"""
AgentMetrics — TDAD adım zamanlaması ve tier dağılımı izleyici.

Thread-safe in-memory collector; GET /v1/agent/metrics endpoint için.
Servis yeniden başlatıldığında sıfırlanır (kalıcı metrik için Prometheus kullanın).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class StepMetric:
    task_id:          str
    step:             str
    tier:             str
    duration_ms:      int
    success:          bool
    reflection_count: int
    timestamp:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MetricsCollector:
    """Thread-safe in-memory metrics store. Son MAX_EVENTS adım kaydını tutar."""

    MAX_EVENTS = 1000

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._events: deque[StepMetric] = deque(maxlen=self.MAX_EVENTS)
        self._step_counts:    dict[str, int]  = defaultdict(int)
        self._step_durations: dict[str, list] = defaultdict(list)
        self._tier_counts:    dict[str, int]  = defaultdict(int)
        self._reflection_total = 0
        self._tasks_started    = 0
        self._tasks_completed  = 0
        self._tasks_failed     = 0

    def record(self, metric: StepMetric) -> None:
        with self._lock:
            self._events.append(metric)
            self._step_counts[metric.step] += 1
            self._step_durations[metric.step].append(metric.duration_ms)
            self._tier_counts[metric.tier] += 1
            self._reflection_total += metric.reflection_count
            if metric.step == "SPEC":
                self._tasks_started += 1
            elif metric.step == "DONE" and metric.success:
                self._tasks_completed += 1
            elif metric.step == "FAILED":
                self._tasks_failed += 1

    def record_step(
        self,
        task_id: str,
        step: str,
        tier: str,
        duration_ms: int,
        success: bool,
        reflection_count: int = 0,
    ) -> None:
        self.record(StepMetric(
            task_id=task_id, step=step, tier=tier,
            duration_ms=duration_ms, success=success,
            reflection_count=reflection_count,
        ))

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            step_stats: Dict[str, Any] = {}
            for step, durations in self._step_durations.items():
                if durations:
                    step_stats[step] = {
                        "count":  self._step_counts[step],
                        "avg_ms": round(sum(durations) / len(durations)),
                        "min_ms": min(durations),
                        "max_ms": max(durations),
                        "p95_ms": _percentile(durations, 95),
                    }
            return {
                "tasks": {
                    "started":   self._tasks_started,
                    "completed": self._tasks_completed,
                    "failed":    self._tasks_failed,
                },
                "tiers":  dict(self._tier_counts),
                "steps":  step_stats,
                "reflections": {
                    "total":         self._reflection_total,
                    "avg_per_task":  round(
                        self._reflection_total / max(self._tasks_started, 1), 2
                    ),
                },
                "recent_events": len(self._events),
            }

    def recent(self, n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            events = list(self._events)[-n:]
        return [
            {
                "task_id":          e.task_id,
                "step":             e.step,
                "tier":             e.tier,
                "duration_ms":      e.duration_ms,
                "success":          e.success,
                "reflection_count": e.reflection_count,
                "timestamp":        e.timestamp.isoformat(),
            }
            for e in events
        ]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._step_counts.clear()
            self._step_durations.clear()
            self._tier_counts.clear()
            self._reflection_total = 0
            self._tasks_started    = 0
            self._tasks_completed  = 0
            self._tasks_failed     = 0


def _percentile(data: list, pct: int) -> int:
    if not data:
        return 0
    s = sorted(data)
    return s[max(0, int(len(s) * pct / 100) - 1)]


_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


class StepTimer:
    """
    Async context manager — TDAD adımlarını zamanlar ve MetricsCollector'a kaydeder.

        async with StepTimer(collector, task_id, "EDIT", "TIER_CHEAP") as t:
            ...  # iş burada
            t.success = True
    """

    def __init__(
        self,
        collector: MetricsCollector,
        task_id: str,
        step: str,
        tier: str,
        reflection_count: int = 0,
    ) -> None:
        self._collector        = collector
        self._task_id          = task_id
        self._step             = step
        self._tier             = tier
        self._reflection_count = reflection_count
        self._start: float     = 0.0
        self.success: bool     = False

    async def __aenter__(self) -> "StepTimer":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        duration_ms = int((time.monotonic() - self._start) * 1000)
        if exc_type is not None:
            self.success = False
        self._collector.record_step(
            task_id=self._task_id,
            step=self._step,
            tier=self._tier,
            duration_ms=duration_ms,
            success=self.success,
            reflection_count=self._reflection_count,
        )
        return False
