"""
Resilience — CircuitBreaker + retry_with_backoff.

CircuitBreaker durumları: CLOSED → OPEN → HALF_OPEN → CLOSED
retry_with_backoff: üstel geri çekilme ile async yeniden deneme dekoratörü.

Kullanım:
    cb = CircuitBreaker(name="openrouter")

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def call_llm(...): ...

    result = await cb.call(call_llm, ...)
"""

from __future__ import annotations

import asyncio
import functools
import time
from enum import Enum
from typing import Any, Callable, Optional, Type

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED    = "CLOSED"     # Normal — istekler geçer
    OPEN      = "OPEN"       # Devre açık — hızlı başarısızlık
    HALF_OPEN = "HALF_OPEN"  # Test modu — bir istek dener


class CircuitBreakerError(Exception):
    """Devre OPEN durumdayken fırlatılır."""


class CircuitBreaker:
    """
    Üç durumlu devre kesici.

    failure_threshold: OPEN durumuna geçmek için gereken ardışık hata sayısı.
    recovery_timeout:  OPEN → HALF_OPEN geçişi için bekleme süresi (saniye).
    success_threshold: HALF_OPEN → CLOSED geçişi için gereken başarı sayısı.
    """

    def __init__(
        self,
        name:              str   = "default",
        failure_threshold: int   = 5,
        recovery_timeout:  float = 60.0,
        success_threshold: int   = 2,
        exceptions:        tuple = (Exception,),
    ) -> None:
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.success_threshold = success_threshold
        self.exceptions        = exceptions

        self._state:           CircuitState = CircuitState.CLOSED
        self._failure_count:   int          = 0
        self._success_count:   int          = 0
        self._last_failure_at: float        = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_at >= self.recovery_timeout:
                self._state         = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("CircuitBreaker[%s]: OPEN → HALF_OPEN", self.name)
        return self._state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        state = self.state
        if state == CircuitState.OPEN:
            raise CircuitBreakerError(
                f"CircuitBreaker[{self.name}] OPEN — istek reddedildi"
            )
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.exceptions as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state         = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("CircuitBreaker[%s]: HALF_OPEN → CLOSED", self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count   += 1
        self._last_failure_at  = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("CircuitBreaker[%s]: HALF_OPEN → OPEN (test başarısız)", self.name)
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "CircuitBreaker[%s]: CLOSED → OPEN (%d ardışık hata)",
                self.name, self._failure_count,
            )

    def reset(self) -> None:
        self._state         = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0

    def stats(self) -> dict:
        return {
            "name":            self.name,
            "state":           self.state.value,
            "failure_count":   self._failure_count,
            "last_failure_at": self._last_failure_at,
        }


# ── Retry dekoratörü ──────────────────────────────────────────────────────────

def retry_with_backoff(
    max_retries:        int            = 3,
    base_delay:         float          = 1.0,
    max_delay:          float          = 30.0,
    backoff_factor:     float          = 2.0,
    jitter:             bool           = True,
    retryable_exceptions: tuple        = (Exception,),
    non_retryable:      tuple          = (CircuitBreakerError,),
) -> Callable:
    """
    Üstel geri çekilme + jitter ile async yeniden deneme dekoratörü.

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def flaky_call(): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            delay = base_delay
            last_exc: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except non_retryable:
                    raise
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    actual_delay = min(delay, max_delay)
                    if jitter:
                        import random
                        actual_delay *= (0.5 + random.random())
                    logger.warning(
                        "retry_with_backoff[%s]: attempt %d/%d başarısız, %.1fs bekliyor. Hata: %s",
                        func.__name__, attempt + 1, max_retries, actual_delay, exc,
                    )
                    await asyncio.sleep(actual_delay)
                    delay *= backoff_factor

            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator


# ── Singleton circuit breaker'lar ─────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name:              str   = "default",
    failure_threshold: int   = 5,
    recovery_timeout:  float = 60.0,
) -> CircuitBreaker:
    """Adlandırılmış singleton circuit breaker döner."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _breakers[name]


def all_breaker_stats() -> list[dict]:
    return [cb.stats() for cb in _breakers.values()]
