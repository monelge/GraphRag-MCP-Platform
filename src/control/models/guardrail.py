"""
Cost Guardrail — LLM çağrılarını ve token kullanımını sınırlar.

Üretim ortamında kontrolsüz LLM çağrısı:
  - beklenmedik maliyet artışına,
  - yüksek latency'ye,
  - cascade timeout hatalarına yol açar.

Bu modül şunları sağlar:
  1. MAX_AUX_LLM_CALLS: search_code içinde opsiyonel LLM çağrı sayısı (rewrite, HyDE)
  2. MAX_TOTAL_LLM_CALLS: tek request içinde toplam LLM çağrısı (aux + final answer)
  3. TOKEN_HARD_LIMIT: context'e gönderilecek maksimum token
  4. MAX_RETRIEVAL_RETRIES: HybridSearch retry sayısı
  5. fail_fast(): token tahmini bütçeyi aşıyorsa exception fırlat

Konfigürasyon (env):
  GUARDRAIL_MAX_AUX_LLM_CALLS   (varsayılan: 1)
  GUARDRAIL_MAX_TOTAL_LLM_CALLS (varsayılan: 2)
  GUARDRAIL_TOKEN_HARD_LIMIT    (varsayılan: 5000)
  GUARDRAIL_MAX_RETRIEVAL_RETRIES (varsayılan: 2)
  GUARDRAIL_ENABLED             (varsayılan: true)
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("GUARDRAIL_ENABLED", "true").lower() != "false"
MAX_AUX_LLM_CALLS        = int(os.getenv("GUARDRAIL_MAX_AUX_LLM_CALLS", "1"))
MAX_TOTAL_LLM_CALLS      = int(os.getenv("GUARDRAIL_MAX_TOTAL_LLM_CALLS", "2"))
TOKEN_HARD_LIMIT         = int(os.getenv("GUARDRAIL_TOKEN_HARD_LIMIT", "5000"))
MAX_RETRIEVAL_RETRIES    = int(os.getenv("GUARDRAIL_MAX_RETRIEVAL_RETRIES", "2"))


class GuardrailError(Exception):
    """Guardrail limiti aşıldığında fırlatılır."""


@dataclass
class RequestBudget:
    """
    Tek bir MCP request boyunca harcamaları takip eder.
    Thread-safe (aynı request'te concurrent kullanım için).

    Kullanım:
        budget = RequestBudget()
        budget.consume_aux_llm("query_rewrite")  # raises if exceeded
        budget.consume_aux_llm("hyde")           # raises if 2nd aux call
        budget.consume_final_llm("explain")      # final answer LLM çağrısı
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
        if not _ENABLED:
            return
        with self._lock:
            if self._aux_calls >= MAX_AUX_LLM_CALLS:
                raise GuardrailError(
                    f"AUX LLM call limiti aşıldı ({self._aux_calls}/{MAX_AUX_LLM_CALLS}). "
                    f"Reddedilen: '{purpose}'"
                )
            if self._total_calls >= MAX_TOTAL_LLM_CALLS:
                raise GuardrailError(
                    f"Toplam LLM call limiti aşıldı ({self._total_calls}/{MAX_TOTAL_LLM_CALLS}). "
                    f"Reddedilen: '{purpose}'"
                )
            self._aux_calls += 1
            self._total_calls += 1
            logger.debug("AUX LLM call: %s (%d/%d aux)", purpose, self._aux_calls, MAX_AUX_LLM_CALLS)

    def consume_final_llm(self, purpose: str) -> None:
        """
        Final answer LLM çağrısı (explain_code, search_code answer) tüketir.
        Aux sayacını artırmaz.
        """
        if not _ENABLED:
            return
        with self._lock:
            if self._total_calls >= MAX_TOTAL_LLM_CALLS:
                raise GuardrailError(
                    f"Toplam LLM call limiti aşıldı ({self._total_calls}/{MAX_TOTAL_LLM_CALLS}). "
                    f"Reddedilen final: '{purpose}'"
                )
            self._total_calls += 1
            logger.debug("Final LLM call: %s (%d/%d total)", purpose, self._total_calls, MAX_TOTAL_LLM_CALLS)

    def consume_retrieval_retry(self) -> None:
        """
        Retrieval retry tüketir. Limit aşılırsa GuardrailError fırlatır.
        """
        if not _ENABLED:
            return
        with self._lock:
            if self._retrieval_retries >= MAX_RETRIEVAL_RETRIES:
                raise GuardrailError(
                    f"Retrieval retry limiti aşıldı ({self._retrieval_retries}/{MAX_RETRIEVAL_RETRIES})"
                )
            self._retrieval_retries += 1

    @property
    def aux_remaining(self) -> int:
        return max(0, MAX_AUX_LLM_CALLS - self._aux_calls)

    @property
    def total_remaining(self) -> int:
        return max(0, MAX_TOTAL_LLM_CALLS - self._total_calls)


def fail_fast_token(token_estimate: int, context: str = "") -> None:
    """
    Token tahmini hard limit'i aşıyorsa GuardrailError fırlatır.
    LLM çağrısından ÖNCE çağrılmalı.

    context: hata mesajına eklenir (debug için).
    """
    if not _ENABLED:
        return
    if token_estimate > TOKEN_HARD_LIMIT:
        raise GuardrailError(
            f"Token hard limit aşıldı: {token_estimate} > {TOKEN_HARD_LIMIT} "
            f"[{context}]. LLM çağrısı iptal edildi."
        )
