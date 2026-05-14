"""Tekrarlanan küçük yardımcı fonksiyonlar."""

from __future__ import annotations

import hashlib
import re
import time


_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([^\s'\"]+)"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
]


def truncate(text: str, max_len: int = 80) -> str:
    """Metni güvenli uzunlukta keser."""
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 3)] + "..."


def redact_secrets(text: str) -> str:
    """Basit secret pattern'lerini maskeleyerek metni döndürür."""
    redacted = text or ""
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).replace(match.group(2), "***"), redacted)
    return redacted


def sha256_hash(text: str) -> str:
    """Metnin SHA-256 hash değerini üretir."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def now_ts() -> float:
    """Tek noktadan zaman damgası üretir."""
    return time.time()
