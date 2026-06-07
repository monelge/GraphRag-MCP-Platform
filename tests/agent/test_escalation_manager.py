"""
EscalationManager birim testleri.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.control.models.complexity_router import ModelTier
from src.control.models.escalation_manager import (
    EscalationAction,
    EscalationManager,
    EscalationState,
)


@pytest.fixture
def manager() -> EscalationManager:
    return EscalationManager()


@pytest.fixture
def state_cheap() -> EscalationState:
    return EscalationState(task_id="t1", current_tier=ModelTier.CHEAP)


@pytest.fixture
def state_local() -> EscalationState:
    return EscalationState(task_id="t2", current_tier=ModelTier.LOCAL)


@pytest.fixture
def state_reason() -> EscalationState:
    return EscalationState(task_id="t3", current_tier=ModelTier.REASON)


# ── Aşama 1: reflection < 2 ───────────────────────────────────────────────────

class TestPhase1:
    def test_reflection_0_retry_same(self, manager, state_cheap):
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.RETRY_SAME
        assert result.new_tier == ModelTier.CHEAP
        assert result.widen_context is False

    def test_reflection_1_retry_same(self, manager, state_cheap):
        state_cheap.reflection_count = 1
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.RETRY_SAME
        assert result.widen_context is False


# ── Aşama 2: 2 ≤ reflection < 4 ─────────────────────────────────────────────

class TestPhase2:
    def test_reflection_2_escalates_cheap_to_reason(self, manager, state_cheap):
        state_cheap.reflection_count = 2
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.ESCALATE
        assert result.new_tier == ModelTier.REASON
        assert result.widen_context is True

    def test_reflection_2_escalates_local_to_cheap(self, manager, state_local):
        state_local.reflection_count = 2
        result = manager.decide(state_local)
        assert result.action == EscalationAction.ESCALATE
        assert result.new_tier == ModelTier.CHEAP
        assert result.widen_context is True

    def test_reflection_3_still_escalate(self, manager, state_cheap):
        state_cheap.reflection_count = 3
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.ESCALATE


# ── Aşama 3: 4 ≤ reflection < 6 ─────────────────────────────────────────────

class TestPhase3:
    def test_reflection_4_forces_reason(self, manager, state_cheap):
        state_cheap.reflection_count = 4
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.FORCE_REASON
        assert result.new_tier == ModelTier.REASON
        assert result.widen_context is True

    def test_reflection_5_forces_reason(self, manager, state_local):
        state_local.reflection_count = 5
        result = manager.decide(state_local)
        assert result.action == EscalationAction.FORCE_REASON


# ── Aşama 4: reflection ≥ 6 → HUMAN_REVIEW ───────────────────────────────────

class TestPhase4:
    def test_reflection_6_human_review(self, manager, state_cheap):
        state_cheap.reflection_count = 6
        result = manager.decide(state_cheap)
        assert result.action == EscalationAction.HUMAN_REVIEW
        assert result.widen_context is False

    def test_needs_human_review_over_max(self, manager, state_cheap):
        state_cheap.reflection_count = 10
        assert manager.needs_human_review(state_cheap) is True

    def test_needs_human_review_below_max(self, manager, state_cheap):
        state_cheap.reflection_count = 3
        assert manager.needs_human_review(state_cheap) is False


# ── Token bütçesi hesaplama ───────────────────────────────────────────────────

class TestTokenBudget:
    def test_cheap_no_widen(self, manager):
        budget = manager.token_budget_for(ModelTier.CHEAP, widen=False)
        assert budget == 16000

    def test_cheap_with_widen(self, manager):
        budget = manager.token_budget_for(ModelTier.CHEAP, widen=True)
        assert budget == 32000  # bir üst tier = REASON

    def test_reason_always_32k(self, manager):
        budget = manager.token_budget_for(ModelTier.REASON, widen=True)
        assert budget == 32000


# ── record_failure kayıt testi ────────────────────────────────────────────────

class TestRecordFailure:
    def test_record_failure_increments_count(self):
        state = EscalationState(task_id="t1", current_tier=ModelTier.CHEAP)
        state.record_failure("test failed: AssertionError")
        assert state.reflection_count == 1
        assert len(state.last_failures) == 1

    def test_last_failures_capped_at_10(self):
        state = EscalationState(task_id="t1", current_tier=ModelTier.CHEAP)
        for i in range(15):
            state.record_failure(f"error {i}")
        assert len(state.last_failures) == 10


# ── Memory kayıt (mock) ───────────────────────────────────────────────────────

class TestMemoryRecording:
    @pytest.mark.asyncio
    async def test_record_success_calls_memory(self, manager):
        memory = AsyncMock()
        memory.store_memory = AsyncMock(return_value=None)
        state = EscalationState(task_id="t1", current_tier=ModelTier.CHEAP)
        await manager.record_success(state, "Fix auth bug", memory_handler=memory)
        memory.store_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_success_no_memory_handler(self, manager):
        state = EscalationState(task_id="t1", current_tier=ModelTier.CHEAP)
        # memory_handler=None → hata fırlatmamalı
        await manager.record_success(state, "Fix auth bug", memory_handler=None)
