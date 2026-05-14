"""İş yüküne göre model seçimi yapan merkezi yönlendirici."""

from __future__ import annotations

from src.shared.config import config

ROUTING_TABLE = {
    "classify": "local",
    "rerank": "local",
    "answerability": "local",
    "deduplicate": "local",
    "query_rewrite": "analysis_model",
    "summarize": "analysis_model",
    "explain": "analysis_model",
    "architecture": "reasoning_model",
    "broad_analysis": "reasoning_model",
}


def get_model(task: str):
    routing = ROUTING_TABLE.get(task, "analysis_model")
    if routing == "local":
        return None
    return getattr(config, routing, config.analysis_model)


def is_local(task: str) -> bool:
    return get_model(task) is None
