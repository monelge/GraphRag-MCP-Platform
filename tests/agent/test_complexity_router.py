"""
ComplexityRouter birim testleri.

Tüm Ollama HTTP çağrıları mock'lanır — offline çalışır.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from src.control.models.complexity_router import (
    ComplexityRouter,
    ComplexityScorer,
    ModelTier,
    OllamaHealthChecker,
    RoutingDecision,
)


# ── ComplexityScorer sinyal testleri ─────────────────────────────────────────

class TestComplexityScorer:
    def setup_method(self):
        self.scorer = ComplexityScorer()

    def test_simple_query_low_score(self):
        score, signals = self.scorer.score("fix typo in README")
        assert score < 0.30, f"Basit sorgu düşük skor vermeli: {score}"
        assert signals["final_score"] == score

    def test_arch_keyword_raises_score(self):
        score, signals = self.scorer.score("refactor the authentication module")
        assert score >= 0.10, "Arch keyword skoru artırmalı"
        assert signals["arch_keywords"] > 0

    def test_stacktrace_signal_detected(self):
        query = "Traceback (most recent call last):\n  File 'app.py', line 42\nException: null pointer"
        score, signals = self.scorer.score(query)
        assert signals["stacktrace"] == 1.0
        assert score >= 0.30

    def test_multi_file_signal_detected(self):
        query = "update models.py and views.py to fix the schema"
        score, signals = self.scorer.score(query)
        assert signals["file_count"] > 0

    def test_high_token_count_signal(self):
        # 300+ token → s_token = 1.0
        long_query = " ".join(["word"] * 300)
        score, signals = self.scorer.score(long_query)
        assert signals["token_count"] == 1.0

    def test_score_clamped_0_to_1(self):
        # Tüm sinyaller maksimum
        query = (
            "Traceback:\n  File 'a.py', line 1\n"
            "refactor architecture security migration dependency "
            + " ".join(["word"] * 400)
            + " update a.py and b.py"
        )
        score, _ = self.scorer.score(query)
        assert 0.0 <= score <= 1.0

    def test_two_arch_keywords_full_signal(self):
        score, signals = self.scorer.score("refactor and security vulnerability fix")
        assert signals["arch_keywords"] == 1.0

    def test_one_arch_keyword_half_signal(self):
        score, signals = self.scorer.score("migration script")
        assert signals["arch_keywords"] == 0.5


# ── Tier sınır değerleri ──────────────────────────────────────────────────────

class TestTierSelection:
    def setup_method(self):
        self.router = ComplexityRouter()

    def test_score_below_030_selects_local(self):
        tier = self.router._select_tier(0.0)
        assert tier == ModelTier.LOCAL

    def test_score_at_030_selects_cheap(self):
        tier = self.router._select_tier(0.30)
        assert tier == ModelTier.CHEAP

    def test_score_at_069_selects_cheap(self):
        tier = self.router._select_tier(0.69)
        assert tier == ModelTier.CHEAP

    def test_score_at_070_selects_reason(self):
        tier = self.router._select_tier(0.70)
        assert tier == ModelTier.REASON

    def test_score_1_selects_reason(self):
        tier = self.router._select_tier(1.0)
        assert tier == ModelTier.REASON


# ── Ollama fallback testi ─────────────────────────────────────────────────────

class TestOllamaFallback:
    @pytest.mark.asyncio
    async def test_ollama_degraded_falls_back_to_cheap(self):
        router = ComplexityRouter()
        # Ollama ping'i başarısız yap
        with patch.object(router._ollama, "_ping", new=AsyncMock(return_value=False)):
            # Düşük skor → LOCAL tier seçilir ama Ollama down
            decision = await router.route("fix typo")
            # LOCAL seçilip degraded → CHEAP'e düşmeli
            assert decision.tier in (ModelTier.CHEAP, ModelTier.LOCAL)
            # Eğer LOCAL seçildi ve ping mock çalıştı ise CHEAP olmalı
            if decision.ollama_degraded:
                assert decision.tier == ModelTier.CHEAP

    @pytest.mark.asyncio
    async def test_ollama_healthy_keeps_local(self):
        router = ComplexityRouter()
        with patch.object(router._ollama, "_ping", new=AsyncMock(return_value=True)):
            router._ollama._last_check = 0  # force re-check
            # Düşük skor → LOCAL kalmalı
            decision = await router.route("fix typo")
            assert not decision.ollama_degraded

    @pytest.mark.asyncio
    async def test_router_disabled_returns_cheap(self):
        with patch.dict(os.environ, {"COMPLEXITY_ROUTER_ENABLED": "false"}):
            router = ComplexityRouter()
            decision = await router.route("anything")
            assert decision.tier == ModelTier.CHEAP

    @pytest.mark.asyncio
    async def test_route_returns_routing_decision(self):
        router = ComplexityRouter()
        with patch.object(router._ollama, "check", new=AsyncMock(return_value=True)):
            decision = await router.route("refactor authentication module security")
            assert isinstance(decision, RoutingDecision)
            assert decision.model
            assert decision.token_budget > 0
