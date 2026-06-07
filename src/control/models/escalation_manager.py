"""
Escalation Manager — 4 aşamalı, reflection tabanlı tier yükseltme.

Aşama 1 (reflection < 2)  : Aynı tier, aynı context → tekrar dene
Aşama 2 (reflection == 2)  : Tier yükselt + context genişlet
Aşama 3 (reflection == 4)  : TIER_REASON + 32K context zorla
Aşama 4 (reflection  > 5)  : HUMAN_REVIEW gerekli

Başarı sonrası mevcut tier ve çözüm memory'ye kaydedilir (öğrenme sinyali).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.control.models.complexity_router import ModelTier, get_complexity_router
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

MAX_REFLECTIONS: int = int(os.getenv("CODEACT_MAX_REFLECTIONS", "5"))


class EscalationAction(str, Enum):
    RETRY_SAME       = "retry_same"        # Aşama 1: aynı tier, tekrar dene
    ESCALATE         = "escalate"          # Aşama 2: tier yükselt
    FORCE_REASON     = "force_reason"      # Aşama 3: TIER_REASON'a zorla
    HUMAN_REVIEW     = "human_review"      # Aşama 4: insan müdahalesi


@dataclass
class EscalationResult:
    action:        EscalationAction
    new_tier:      ModelTier
    widen_context: bool           # True ise context assembler bütçeyi genişletir
    reflection:    int
    reason:        str


@dataclass
class EscalationState:
    """Bir görevin escalation durumunu tutar."""
    task_id:          str
    current_tier:     ModelTier
    reflection_count: int = 0
    last_failures:    list[str] = field(default_factory=list)

    def record_failure(self, error_summary: str) -> None:
        self.reflection_count += 1
        self.last_failures.append(error_summary[:200])
        if len(self.last_failures) > 10:
            self.last_failures.pop(0)


class EscalationManager:
    """Reflection sayısına göre bir sonraki aksiyonu hesaplar."""

    def decide(self, state: EscalationState) -> EscalationResult:
        r = state.reflection_count

        if r < 2:
            # Aşama 1: aynı tier, prompt ile tekrar dene
            return EscalationResult(
                action=EscalationAction.RETRY_SAME,
                new_tier=state.current_tier,
                widen_context=False,
                reflection=r,
                reason=f"Aşama 1 — aynı tier ({state.current_tier.value}), reflection {r}/2",
            )

        if r < 4:
            # Aşama 2: bir üst tier + context genişlet
            elevated = self._elevate(state.current_tier)
            return EscalationResult(
                action=EscalationAction.ESCALATE,
                new_tier=elevated,
                widen_context=True,
                reflection=r,
                reason=f"Aşama 2 — {state.current_tier.value} → {elevated.value}, context genişletiliyor",
            )

        if r < 6:
            # Aşama 3: TIER_REASON'a zorla + 32K context
            return EscalationResult(
                action=EscalationAction.FORCE_REASON,
                new_tier=ModelTier.REASON,
                widen_context=True,
                reflection=r,
                reason=f"Aşama 3 — TIER_REASON'a zorlandı, 32K context",
            )

        # Aşama 4: insan müdahalesi
        return EscalationResult(
            action=EscalationAction.HUMAN_REVIEW,
            new_tier=state.current_tier,
            widen_context=False,
            reflection=r,
            reason=f"Aşama 4 — max reflection ({MAX_REFLECTIONS}) aşıldı, HUMAN_REVIEW gerekli",
        )

    def needs_human_review(self, state: EscalationState) -> bool:
        return state.reflection_count > MAX_REFLECTIONS

    async def record_success(
        self,
        state: EscalationState,
        goal_summary: str,
        memory_handler=None,
    ) -> None:
        """Başarılı tamamlanmada tier bilgisini memory'ye yazar."""
        if memory_handler is None:
            return
        try:
            content = (
                f"Görev '{goal_summary[:120]}' başarıyla {state.current_tier.value} "
                f"ile {state.reflection_count} reflection sonrası çözüldü."
            )
            await memory_handler.store_memory(
                title=f"Başarılı çözüm: {goal_summary[:60]}",
                content=content,
                collection="agent_learning",
            )
            logger.debug("Escalation success memory kaydedildi: %s", goal_summary[:60])
        except Exception as exc:
            logger.warning("Escalation success memory yazılamadı: %s", exc)

    async def record_failure(
        self,
        state: EscalationState,
        error_summary: str,
        memory_handler=None,
    ) -> None:
        """Başarısızlık örüntüsünü memory'ye yazar."""
        if memory_handler is None:
            return
        try:
            content = (
                f"Pattern {state.current_tier.value}'da başarısız oldu "
                f"(reflection={state.reflection_count}): {error_summary[:200]}"
            )
            await memory_handler.store_memory(
                title=f"Başarısız pattern [{state.current_tier.value}]",
                content=content,
                collection="agent_learning",
            )
        except Exception as exc:
            logger.warning("Escalation failure memory yazılamadı: %s", exc)

    @staticmethod
    def _elevate(tier: ModelTier) -> ModelTier:
        if tier == ModelTier.LOCAL:
            return ModelTier.CHEAP
        return ModelTier.REASON

    def token_budget_for(self, tier: ModelTier, widen: bool = False) -> int:
        """Tier ve context genişleme durumuna göre token bütçesi döner."""
        router = get_complexity_router()
        cfg = router.get_config(tier)
        if widen and tier != ModelTier.REASON:
            # Bir üst tier'ın bütçesini kullan
            upper = self._elevate(tier)
            return router.get_config(upper).token_budget
        return cfg.token_budget
