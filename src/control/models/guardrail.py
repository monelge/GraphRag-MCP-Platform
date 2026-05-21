"""
Cost Guardrail — LLM çağrılarını ve token kullanımını sınırlar.

Üretim ortamında kontrolsüz LLM çağrısı:
  - beklenmedik maliyet artışına,
  - yüksek latency'ye,
  - cascade timeout hatalarına yol açar.

Konfigürasyon (env):
  GUARDRAIL_MAX_AUX_LLM_CALLS   (config üzerinden)
  GUARDRAIL_MAX_TOTAL_LLM_CALLS (config üzerinden)
  GUARDRAIL_TOKEN_HARD_LIMIT    (config üzerinden)
  GUARDRAIL_MAX_RETRIEVAL_RETRIES (config üzerinden)
  GUARDRAIL_ENABLED             (config üzerinden)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from src.shared.config import config

logger = logging.getLogger(__name__)


class GuardrailError(Exception):
    """Guardrail limiti aşıldığında fırlatılır."""


@dataclass
class RequestBudget:
    """
    Tek bir MCP request boyunca harcamaları takip eder.
    Thread-safe (aynı request'te concurrent kullanım için).
    """
    _aux_calls: int = field(default=0, init=False)
    _total_calls: int = field(default=0, init=False)
    _retrieval_retries: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def consume_aux_llm(self, purpose: str) -> None:
        """
        Yardımcı LLM çağrısı (rewrite, HyDE, vb.) tüketir.
        Limit aşılırsa GuardrailError fırlatır.
        """
        if not config.guardrail_enabled:
            return
        with self._lock:
            if self._aux_calls >= config.guardrail_max_aux_llm_calls:
                raise GuardrailError(
                    f"AUX LLM call limiti aşıldı ({self._aux_calls}/{config.guardrail_max_aux_llm_calls}). "
                    f"Reddedilen: '{purpose}'"
                )
            if self._total_calls >= config.guardrail_max_total_llm_calls:
                raise GuardrailError(
                    f"Toplam LLM call limiti aşıldı ({self._total_calls}/{config.guardrail_max_total_llm_calls}). "
                    f"Reddedilen: '{purpose}'"
                )
            self._aux_calls += 1
            self._total_calls += 1
            logger.debug("AUX LLM call: %s (%d/%d aux)", purpose, self._aux_calls, config.guardrail_max_aux_llm_calls)

    def consume_final_llm(self, purpose: str) -> None:
        """
        Final answer LLM çağrısı (explain_code, search_code answer) tüketir.
        Aux sayacını artırmaz.
        """
        if not config.guardrail_enabled:
            return
        with self._lock:
            if self._total_calls >= config.guardrail_max_total_llm_calls:
                raise GuardrailError(
                    f"Toplam LLM call limiti aşıldı ({self._total_calls}/{config.guardrail_max_total_llm_calls}). "
                    f"Reddedilen final: '{purpose}'"
                )
            self._total_calls += 1
            logger.debug("Final LLM call: %s (%d/%d total)", purpose, self._total_calls, config.guardrail_max_total_llm_calls)

    def consume_retrieval_retry(self) -> None:
        """
        Retrieval retry tüketir. Limit aşılırsa GuardrailError fırlatır.
        """
        if not config.guardrail_enabled:
            return
        with self._lock:
            if self._retrieval_retries >= config.guardrail_max_retrieval_retries:
                raise GuardrailError(
                    f"Retrieval retry limiti aşıldı ({self._retrieval_retries}/{config.guardrail_max_retrieval_retries})"
                )
            self._retrieval_retries += 1

    @property
    def aux_remaining(self) -> int:
        return max(0, config.guardrail_max_aux_llm_calls - self._aux_calls)

    @property
    def total_remaining(self) -> int:
        return max(0, config.guardrail_max_total_llm_calls - self._total_calls)


def fail_fast_token(token_estimate: int, context: str = "") -> None:
    """
    Token tahmini hard limit'i aşıyorsa GuardrailError fırlatır.
    LLM çağrısından ÖNCE çağrılmalı.
    """
    if not config.guardrail_enabled:
        return
    if token_estimate > config.guardrail_token_hard_limit:
        raise GuardrailError(
            f"Token hard limit aşıldı: {token_estimate} > {config.guardrail_token_hard_limit} "
            f"[{context}]. LLM çağrısı iptal edildi."
        )
