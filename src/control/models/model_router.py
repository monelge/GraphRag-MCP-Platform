"""İş yüküne göre model seçimi yapan merkezi yönlendirici.

Katmanlar:
  local          → LLM yok (CrossEncoder, classifier, yerel model)
  budget_model   → Ücretsiz/ucuz  (query rewrite, HyDE, memory compact)
  analysis_model → Orta           (explain, summarize, test/security öneri)
  reasoning_model → Güçlü         (mimari karar, broad analysis)
"""

from __future__ import annotations

from src.shared.config import config

ROUTING_TABLE = {
    # ── Yerel — LLM çağrısı yok ───────────────────────────────────────────
    "classify":        "local",
    "rerank":          "local",
    "answerability":   "local",
    "deduplicate":     "local",

    # ── Budget — ücretsiz/ucuz model ──────────────────────────────────────
    "query_rewrite":   "budget_model",   # HybridSearcher öncesi sorgu genişletme
    "hyde":            "budget_model",   # Hypothetical Document Embedding
    "memory_compact":  "budget_model",   # compact_memory / run_memory_cycle özetleri
    "fact_extract":    "budget_model",   # atomic fact çıkarımı

    # ── Analysis — orta model ─────────────────────────────────────────────
    "summarize":       "analysis_model", # repo / kod özeti
    "explain":         "analysis_model", # explain_code
    "security":        "analysis_model", # security_scan bulgu yorumu
    "test_suggest":    "analysis_model", # test_suggestion üretimi
    "refactor":        "analysis_model", # refactor_suggestions

    # ── Reasoning — güçlü model ───────────────────────────────────────────
    "architecture":    "reasoning_model", # search_repo_architecture yorumu
    "broad_analysis":  "reasoning_model", # geniş kapsam analizi
    "execute_plan":    "reasoning_model", # execute_agent_task planlama
}


def get_model(task: str) -> str | None:
    """Görev tipine göre model kimliğini döner. Yerel görevler için None."""
    routing = ROUTING_TABLE.get(task, "analysis_model")
    if routing == "local":
        return None
    return getattr(config, routing, config.analysis_model)


def is_local(task: str) -> bool:
    return get_model(task) is None


def get_tier(task: str) -> str:
    """Görevin hangi katmana düştüğünü döner (loglama / metrik için)."""
    routing = ROUTING_TABLE.get(task, "analysis_model")
    if routing == "local":
        return "local"
    if routing == "budget_model":
        return "budget"
    if routing == "reasoning_model":
        return "reasoning"
    return "analysis"
