"""
Pipeline Tracer — Retrieval pipeline adımlarını izler ve loglar.

Neden tracing?
  Metrics (latency, cache hit ratio) tek başına yetersizdir.
  "Neden yanlış sonuç geldi?" sorusunu yanıtlamak için her adımın
  ara çıktısının kayıt altına alınması gerekir.

İzlenen adımlar:
  retrieval, rerank, graph_expand, dedup, token_budget,
  context_build, hyde, compress, answerability

Kullanım:
    tracer = PipelineTracer(query="login neden düşüyor", collection="Vendoris")
    with tracer.step("retrieval"):
        results = await searcher.search(...)
        tracer.record("retrieval", item_count=len(results), top1_score=0.72)
    ...
    summary = tracer.finish()
    await postgres.log_trace(summary)

Güvenlik:
  Ham chunk içeriği veya kaynak kodu loglanmaz.
  Sadece sayısal metrikler ve adım adları yazılır.
"""

from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepTrace:
    """Tek bir pipeline adımına ait trace kaydı."""
    name: str
    started_at: float
    ended_at: float = 0.0
    latency_ms: int = 0
    item_count: int = 0
    token_count: int = 0
    metadata: dict = field(default_factory=dict)
    error: str = ""

    def finish(self) -> None:
        self.ended_at = time.monotonic()
        self.latency_ms = int((self.ended_at - self.started_at) * 1000)


class PipelineTracer:
    """
    Retrieval pipeline'ının başından sonuna tüm adımları kaydeder.
    Her instance tek bir MCP tool çağrısına karşılık gelir.
    """

    def __init__(self, query: str, collection: str, query_type: str = "unknown"):
        self.query = query[:80]          # Ham sorgu metni loglanmaz; sadece ilk 80 char
        self.collection = collection
        self.query_type = query_type
        self._started_at = time.monotonic()
        self._steps: list[StepTrace] = []
        self._active: StepTrace | None = None

    @contextmanager
    def step(self, name: str):
        """
        Context manager olarak pipeline adımını izler.

        Kullanım:
            with tracer.step("rerank"):
                chunks = reranker.rerank(...)
        """
        trace = StepTrace(name=name, started_at=time.monotonic())
        self._active = trace
        try:
            yield trace
        except Exception as exc:
            trace.error = type(exc).__name__
            raise
        finally:
            trace.finish()
            self._steps.append(trace)
            self._active = None
            logger.debug("Trace [%s] %dms items=%d", name, trace.latency_ms, trace.item_count)

    def record(self, step_name: str, **kwargs: Any) -> None:
        """
        Aktif adıma veya adı verilen adıma metadata ekler.
        Desteklenen alanlar: item_count, token_count, + metadata (diğerleri).
        """
        target = self._active
        if target is None or target.name != step_name:
            # Geriye dönük kayıt — son eşleşen adımı bul
            matches = [s for s in self._steps if s.name == step_name]
            target = matches[-1] if matches else None

        if target is None:
            return

        for k, v in kwargs.items():
            if k == "item_count":
                target.item_count = int(v)
            elif k == "token_count":
                target.token_count = int(v)
            else:
                target.metadata[k] = v

    def finish(self) -> dict:
        """
        Tüm trace'i özetleyen dict döner.
        PostgreSQL log_trace() metoduna geçirilmek üzere tasarlanmıştır.
        """
        total_ms = int((time.monotonic() - self._started_at) * 1000)
        return {
            "query_preview": self.query,
            "collection": self.collection,
            "query_type": self.query_type,
            "total_latency_ms": total_ms,
            "steps": [
                {
                    "name": s.name,
                    "latency_ms": s.latency_ms,
                    "item_count": s.item_count,
                    "token_count": s.token_count,
                    "error": s.error,
                    **s.metadata,
                }
                for s in self._steps
            ],
            "failed_steps": [s.name for s in self._steps if s.error],
            "step_count": len(self._steps),
        }
