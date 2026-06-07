"""
Complexity Router — 4 sinyal tabanlı deterministik LLM tier seçici.

Skor: 0.0–1.0
  [0.00, 0.30) → TIER_LOCAL   (Ollama, ücretsiz)
  [0.30, 0.70) → TIER_CHEAP   (OpenRouter ucuz)
  [0.70, 1.00] → TIER_REASON  (Güçlü akıl yürütme)

Ollama HW kontrolü: p95 latency > 5s veya bağlanamıyorsa TIER_LOCAL → TIER_CHEAP.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ── Mimari / karmaşık iş anahtar kelimeleri ───────────────────────────────────
_ARCH_KEYWORDS: frozenset[str] = frozenset({
    "refactor", "refaktör", "yeniden yaz", "rewrite",
    "mimari", "architecture", "tasarla", "design",
    "soyutla", "abstract", "katman", "layer",
    "güvenlik", "security", "vulnerability", "açık",
    "injection", "auth", "authentication", "authorization",
    "migration", "migrate", "şema", "schema",
    "performans", "performance", "optimize", "optimizasyon",
    "deadlock", "race condition", "concurrency",
    "dependency", "bağımlılık", "interface", "arayüz",
})

# ── Stack trace / hata sinyalleri ────────────────────────────────────────────
_STACKTRACE_PATTERNS: list[re.Pattern] = [
    re.compile(r"traceback", re.IGNORECASE),
    re.compile(r"at line \d+"),
    re.compile(r"exception:", re.IGNORECASE),
    re.compile(r"error:", re.IGNORECASE),
    re.compile(r"^\s+file \".*\", line \d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"caused by", re.IGNORECASE),
    re.compile(r"stacktrace|stack trace", re.IGNORECASE),
]

# ── Çok dosya referans sinyalleri ────────────────────────────────────────────
_MULTI_FILE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\w+\.\w{2,4}\b.*\b\w+\.\w{2,4}\b"),  # iki dosya adı
    re.compile(r"\bve\b.+\bdosya", re.IGNORECASE),
    re.compile(r"\band\b.+\bfile", re.IGNORECASE),
    re.compile(r"(güncelle|update|değiştir|modify).+(ve|and)", re.IGNORECASE),
    re.compile(r"tüm (dosyalar|projede|servislerde)", re.IGNORECASE),
    re.compile(r"all (files|services|modules)", re.IGNORECASE),
]


class ModelTier(str, Enum):
    LOCAL  = "TIER_LOCAL"
    CHEAP  = "TIER_CHEAP"
    REASON = "TIER_REASON"


@dataclass(frozen=True)
class TierConfig:
    model:      str
    fallback:   str
    base_url:   Optional[str] = None
    token_budget: int = 8000


@dataclass
class RoutingDecision:
    tier:             ModelTier
    score:            float
    model:            str
    base_url:         Optional[str]
    token_budget:     int
    signals:          dict = field(default_factory=dict)
    ollama_degraded:  bool = False


def _load_tier_configs() -> dict[ModelTier, TierConfig]:
    return {
        ModelTier.LOCAL: TierConfig(
            model=os.getenv("TIER_LOCAL_MODEL", "qwen2.5-coder:32b"),
            fallback=os.getenv("TIER_LOCAL_FALLBACK_MODEL", "deepseek-coder-v2:16b"),
            base_url=os.getenv("TIER_LOCAL_BASE_URL", "http://host.docker.internal:11434/v1"),
            token_budget=int(os.getenv("CONTEXT_BUDGET_LOCAL", "8000")),
        ),
        ModelTier.CHEAP: TierConfig(
            model=os.getenv("TIER_CHEAP_MODEL", "google/gemini-2.5-flash"),
            fallback=os.getenv("TIER_CHEAP_FALLBACK", "mistralai/codestral-latest"),
            base_url=None,
            token_budget=int(os.getenv("CONTEXT_BUDGET_CHEAP", "16000")),
        ),
        ModelTier.REASON: TierConfig(
            model=os.getenv("TIER_REASON_MODEL", "anthropic/claude-sonnet-4-6"),
            fallback=os.getenv("TIER_REASON_FALLBACK", "deepseek/deepseek-v3"),
            base_url=None,
            token_budget=int(os.getenv("CONTEXT_BUDGET_REASON", "32000")),
        ),
    }


class ComplexityScorer:
    """Dört ana sinyal ile 0.0–1.0 skor üretir."""

    LOCAL_THRESHOLD:  float = float(os.getenv("COMPLEXITY_LOCAL_THRESHOLD",  "0.30"))
    REASON_THRESHOLD: float = float(os.getenv("COMPLEXITY_REASON_THRESHOLD", "0.70"))

    def score(self, query: str) -> tuple[float, dict]:
        tokens = self._token_count(query)

        s_file       = self._file_count_signal(query)
        s_stacktrace = self._stacktrace_signal(query)
        s_arch       = self._arch_keyword_signal(query)
        s_token      = self._token_count_signal(tokens)

        raw = (
            0.40 * s_file
            + 0.30 * s_stacktrace
            + 0.20 * s_arch
            + 0.10 * s_token
        )
        final = min(max(raw, 0.0), 1.0)

        signals = {
            "file_count":   round(s_file, 3),
            "stacktrace":   round(s_stacktrace, 3),
            "arch_keywords": round(s_arch, 3),
            "token_count":  round(s_token, 3),
            "raw_score":    round(raw, 3),
            "final_score":  round(final, 3),
            "token_count_raw": tokens,
        }
        return final, signals

    # ── Sinyal hesaplayıcıları ─────────────────────────────────────────────

    def _file_count_signal(self, query: str) -> float:
        for pat in _MULTI_FILE_PATTERNS:
            if pat.search(query):
                return 1.0
        # Açık dosya uzantısı sayısı
        extensions = re.findall(r"\b\w+\.\w{2,5}\b", query)
        unique_exts = len(set(extensions))
        if unique_exts >= 3:
            return 1.0
        if unique_exts == 2:
            return 0.6
        return 0.0

    def _stacktrace_signal(self, query: str) -> float:
        for pat in _STACKTRACE_PATTERNS:
            if pat.search(query):
                return 1.0
        return 0.0

    def _arch_keyword_signal(self, query: str) -> float:
        lower = query.lower()
        matched = sum(1 for kw in _ARCH_KEYWORDS if kw in lower)
        if matched == 0:
            return 0.0
        if matched == 1:
            return 0.5
        return 1.0

    def _token_count_signal(self, tokens: int) -> float:
        if tokens >= 300:
            return 1.0
        if tokens >= 150:
            return 0.5
        if tokens >= 80:
            return 0.2
        return 0.0

    @staticmethod
    def _token_count(text: str) -> int:
        # Basit yaklaşım: boşluk sayısı + 1; ortalama 0.75 word/token
        words = len(text.split())
        return int(words / 0.75)


class OllamaHealthChecker:
    """Ollama sunucusunu periyodik olarak kontrol eder."""

    LATENCY_THRESHOLD_MS: int = int(os.getenv("OLLAMA_LATENCY_THRESHOLD_MS", "5000"))
    CHECK_INTERVAL_S:     int = int(os.getenv("OLLAMA_CHECK_INTERVAL_S",     "30"))

    def __init__(self) -> None:
        self._degraded:    bool  = False
        self._last_check:  float = 0.0
        self._base_url:    str   = os.getenv(
            "TIER_LOCAL_BASE_URL", "http://host.docker.internal:11434/v1"
        )

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    async def check(self) -> bool:
        """True döner = Ollama sağlıklı."""
        now = time.monotonic()
        if now - self._last_check < self.CHECK_INTERVAL_S:
            return not self._degraded

        self._last_check = now
        healthy = await self._ping()
        self._degraded = not healthy
        if self._degraded:
            logger.warning("Ollama degraded — TIER_LOCAL istekleri TIER_CHEAP'e yönlendirilecek.")
        return healthy

    async def _ping(self) -> bool:
        try:
            import httpx
            health_url = self._base_url.replace("/v1", "") + "/api/tags"
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=self.LATENCY_THRESHOLD_MS / 1000) as client:
                resp = await client.get(health_url)
            latency_ms = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200 and latency_ms < self.LATENCY_THRESHOLD_MS
            logger.debug("Ollama ping: status=%s latency=%.0fms ok=%s", resp.status_code, latency_ms, ok)
            return ok
        except Exception as exc:
            logger.debug("Ollama ping failed: %s", exc)
            return False


class ComplexityRouter:
    """Ana router: skor üret → tier seç → Ollama HW kontrolü."""

    def __init__(self) -> None:
        self._scorer  = ComplexityScorer()
        self._ollama  = OllamaHealthChecker()
        self._configs = _load_tier_configs()
        self._enabled = os.getenv("COMPLEXITY_ROUTER_ENABLED", "true").lower() == "true"
        self._local_enabled = os.getenv("TIER_LOCAL_ENABLED", "true").lower() == "true"

    async def route(self, query: str) -> RoutingDecision:
        if not self._enabled:
            # Router devre dışıysa varsayılan olarak TIER_CHEAP döner
            cfg = self._configs[ModelTier.CHEAP]
            return RoutingDecision(
                tier=ModelTier.CHEAP, score=0.5, model=cfg.model,
                base_url=cfg.base_url, token_budget=cfg.token_budget,
            )

        score, signals = self._scorer.score(query)
        tier = self._select_tier(score)
        ollama_degraded = False

        # Ollama HW kontrolü
        if tier == ModelTier.LOCAL and self._local_enabled:
            healthy = await self._ollama.check()
            if not healthy:
                tier = ModelTier.CHEAP
                ollama_degraded = True
                logger.info("Ollama degraded → TIER_LOCAL → TIER_CHEAP (score=%.3f)", score)
        elif tier == ModelTier.LOCAL and not self._local_enabled:
            tier = ModelTier.CHEAP

        cfg = self._configs[tier]
        logger.info(
            "ComplexityRouter: score=%.3f tier=%s model=%s signals=%s",
            score, tier.value, cfg.model, signals,
        )
        return RoutingDecision(
            tier=tier, score=score, model=cfg.model,
            base_url=cfg.base_url, token_budget=cfg.token_budget,
            signals=signals, ollama_degraded=ollama_degraded,
        )

    def route_sync(self, query: str) -> RoutingDecision:
        """Async olmayan bağlamlarda kullanım için."""
        score, signals = self._scorer.score(query)
        tier = self._select_tier(score)
        if (tier == ModelTier.LOCAL) and (not self._local_enabled or self._ollama.is_degraded):
            tier = ModelTier.CHEAP
        cfg = self._configs[tier]
        return RoutingDecision(
            tier=tier, score=score, model=cfg.model,
            base_url=cfg.base_url, token_budget=cfg.token_budget,
            signals=signals,
        )

    def get_config(self, tier: ModelTier) -> TierConfig:
        return self._configs[tier]

    def _select_tier(self, score: float) -> ModelTier:
        if score < ComplexityScorer.LOCAL_THRESHOLD:
            return ModelTier.LOCAL
        if score < ComplexityScorer.REASON_THRESHOLD:
            return ModelTier.CHEAP
        return ModelTier.REASON


# Uygulama genelinde tek instance
_router: Optional[ComplexityRouter] = None


def get_complexity_router() -> ComplexityRouter:
    global _router
    if _router is None:
        _router = ComplexityRouter()
    return _router
