"""
Prometheus metrics — /metrics endpoint üzerinden expose edilir.

Mevcut MetricsCollector ile köprü kurulur; Prometheus format ek olarak desteklenir.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_prometheus_available = False
_tool_calls_total = None
_retrieval_latency = None
_rerank_latency = None
_cache_hits_total = None
_active_tool_calls = None
_memory_operations_total = None


def _init_prometheus():
    global _prometheus_available, _tool_calls_total, _retrieval_latency
    global _rerank_latency, _cache_hits_total, _active_tool_calls, _memory_operations_total

    try:
        from prometheus_client import Counter, Histogram, Gauge

        _tool_calls_total = Counter(
            "graphmcp_tool_calls_total",
            "MCP tool çağrı sayısı",
            ["tool", "status"],
        )
        _retrieval_latency = Histogram(
            "graphmcp_retrieval_latency_seconds",
            "Retrieval pipeline latency",
            ["collection", "query_type"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
        )
        _rerank_latency = Histogram(
            "graphmcp_rerank_latency_seconds",
            "Reranking latency",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
        )
        _cache_hits_total = Counter(
            "graphmcp_cache_hits_total",
            "Redis cache hit sayısı",
            ["collection", "cache_type"],
        )
        _active_tool_calls = Gauge(
            "graphmcp_active_tool_calls",
            "Şu an aktif çalışan tool sayısı",
        )
        _memory_operations_total = Counter(
            "graphmcp_memory_operations_total",
            "Memory plane işlem sayısı",
            ["operation", "memory_type"],
        )

        _prometheus_available = True
        logger.info("Prometheus metrics başlatıldı")

    except ImportError:
        logger.debug("prometheus-client yüklü değil, metrics devre dışı")
    except Exception as e:
        logger.warning("Prometheus init hatası: %s", e)


_init_prometheus()


def record_tool_call(tool: str, status: str = "success"):
    if _tool_calls_total:
        try:
            _tool_calls_total.labels(tool=tool, status=status).inc()
        except Exception:
            pass


def record_retrieval(collection: str, latency_ms: float, query_type: str = "hybrid"):
    if _retrieval_latency:
        try:
            _retrieval_latency.labels(
                collection=collection[:32], query_type=query_type
            ).observe(latency_ms / 1000)
        except Exception:
            pass


def record_rerank(latency_ms: float):
    if _rerank_latency:
        try:
            _rerank_latency.observe(latency_ms / 1000)
        except Exception:
            pass


def record_cache_hit(collection: str, cache_type: str = "exact"):
    if _cache_hits_total:
        try:
            _cache_hits_total.labels(collection=collection[:32], cache_type=cache_type).inc()
        except Exception:
            pass


def record_memory_op(operation: str, memory_type: str = "episodic"):
    if _memory_operations_total:
        try:
            _memory_operations_total.labels(operation=operation, memory_type=memory_type).inc()
        except Exception:
            pass


def generate_metrics_response() -> tuple[bytes, str]:
    """Prometheus /metrics endpoint için ham response döner."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return generate_latest(), CONTENT_TYPE_LATEST
    except ImportError:
        return b"# prometheus-client not installed\n", "text/plain"


def is_available() -> bool:
    return _prometheus_available
