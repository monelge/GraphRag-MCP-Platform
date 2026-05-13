"""
Model Router — Her işlem için doğru modeli seçer.

Prensip: "Her işlem GPT-4 seviyesinde çalışmamalı."
  - classify / rerank / answerability → local (Python kodu, sıfır API maliyeti)
  - summarization / explain → gpt-4o-mini (hızlı, ucuz)
  - architecture reasoning / broad analysis → güçlü reasoning model

Yeni model eklemek için sadece ROUTING_TABLE'ı güncelle.
"""

from __future__ import annotations
import os

# ── Routing tablosu ──────────────────────────────────────────────────────────
# Değerler env variable adlarıdır; ayarlanmamışsa DEFAULT değeri kullanılır.

ROUTING_TABLE: dict[str, str] = {
    # Yerel işlemler — API çağrısı yok
    "classify":       "local",
    "rerank":         "local",
    "answerability":  "local",
    "deduplicate":    "local",
    # Hafif LLM işlemleri
    "query_rewrite":  "ANALYSIS_MODEL",          # default: openai/gpt-4o-mini
    "summarize":      "ANALYSIS_MODEL",
    "explain":        "ANALYSIS_MODEL",
    # Ağır reasoning gerektiren işlemler
    "architecture":   "REASONING_MODEL",         # default: openai/o4-mini
    "broad_analysis": "REASONING_MODEL",
}

# Model varsayılanları — env variable ayarlanmamışsa kullanılır
_DEFAULTS: dict[str, str] = {
    "ANALYSIS_MODEL":  "openai/gpt-4o-mini",
    "REASONING_MODEL": "openai/o4-mini",
}


def get_model(task: str) -> str | None:
    """
    Verilen görev için kullanılacak model adını döner.
    "local" dönen görevler için None döner (API çağrısı gerekmez).
    """
    routing = ROUTING_TABLE.get(task, "ANALYSIS_MODEL")

    if routing == "local":
        return None

    # Env variable'dan oku; yoksa default'u kullan
    return os.getenv(routing, _DEFAULTS.get(routing, "openai/gpt-4o-mini"))


def is_local(task: str) -> bool:
    """Görev yerel (API'siz) işlenecekse True döner."""
    return get_model(task) is None
