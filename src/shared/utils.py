"""Tekrarlanan küçük yardımcı fonksiyonlar."""

import hashlib


def sha256_hash(text: str) -> str:
    """Metnin SHA-256 hash değerini üretir."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
