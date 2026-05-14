from __future__ import annotations

"""Araç ve retrieval metriklerini process içinde toplayan basit kolektör."""

from collections import defaultdict
from threading import Lock


class MetricsCollector:
    """Düşük maliyetli in-memory metrik kolektörü."""

    def __init__(self):
        self.tool_call_counts: dict[str, dict[str, int | float]] = defaultdict(
            lambda: {"count": 0, "success": 0, "failure": 0, "latency_ms_total": 0.0}
        )
        self.retrieval_latency_p50: dict[str, float] = {}
        self.error_counts: dict[str, int] = defaultdict(int)
        self._retrieval_latencies: dict[str, list[float]] = defaultdict(list)
        self._retrieval_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "hits": 0, "tokens": 0}
        )
        self._lock = Lock()

    def record_tool_call(self, tool_name: str, latency_ms: int, success: bool) -> None:
        """Araç çağrı sayısını, başarı durumunu ve toplam gecikmeyi kaydeder."""
        with self._lock:
            bucket = self.tool_call_counts[tool_name]
            bucket["count"] += 1
            bucket["latency_ms_total"] += max(latency_ms, 0)
            if success:
                bucket["success"] += 1
            else:
                bucket["failure"] += 1
                self.error_counts[tool_name] += 1

    def record_retrieval(self, collection: str, latency_ms: int, hit_count: int, token_count: int) -> None:
        """Retrieval gecikmesini ve hacim sayaçlarını günceller."""
        key = collection or "default"
        with self._lock:
            self._retrieval_latencies[key].append(max(latency_ms, 0))
            stats = self._retrieval_stats[key]
            stats["calls"] += 1
            stats["hits"] += max(hit_count, 0)
            stats["tokens"] += max(token_count, 0)
            ordered = sorted(self._retrieval_latencies[key])
            mid = len(ordered) // 2
            self.retrieval_latency_p50[key] = float(ordered[mid])

    def get_snapshot(self) -> dict:
        """Anlık sayaç görünümünü döndürür."""
        with self._lock:
            return {
                "tool_call_counts": {key: dict(value) for key, value in self.tool_call_counts.items()},
                "retrieval_latency_p50": dict(self.retrieval_latency_p50),
                "error_counts": dict(self.error_counts),
                "retrieval_stats": {key: dict(value) for key, value in self._retrieval_stats.items()},
            }


_METRICS_SINGLETON: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Process genelinde tek metrics collector instance'ı döndürür."""
    global _METRICS_SINGLETON
    if _METRICS_SINGLETON is None:
        _METRICS_SINGLETON = MetricsCollector()
    return _METRICS_SINGLETON
