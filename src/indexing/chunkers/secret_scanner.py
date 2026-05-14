"""
SecretScanner — Faz 0 §0a Güvenlik Filtresi

Neden bu dosya var?
  Index ve output pipeline'ında sır içerikli chunk'ların Qdrant'a girmesini
  ve LLM'e ulaşmasını engeller. İki katmanlı koruma:
    1. Indexer: risk_score > 0.8 → chunk atlanır, security_skip_log'a düşer
    2. Output redaction: search sonuçları LLM'e gönderilmeden önce bir kez daha taranır
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Güven seviyelerine göre ayrılmış pattern listesi.
# Neden iki seviye?
#   - HIGH_CONFIDENCE: Neredeyse kesin sır (private key, OpenAI key) → tek eşleşme skip
#   - MEDIUM_CONFIDENCE: Bağlama bağlı tehlikeli (base64 uzun string, password=) →
#     redact edilir, sayısı > 2 olunca skip
_HIGH_CONFIDENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN\s*(RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE), "PRIVATE_KEY"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}", re.IGNORECASE), "OPENAI_KEY"),
    (re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE), "BEARER_TOKEN"),
]

_MEDIUM_CONFIDENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE), "PASSWORD"),
    (re.compile(r"connectionstring\s*[=:]\s*\S+", re.IGNORECASE), "CONNECTION_STRING"),
    (re.compile(r"datasource\s*[=:]\s*\S+", re.IGNORECASE), "DATASOURCE"),
    (re.compile(r"server\s*=\s*[^;]{1,80};\s*.*?password\s*=", re.IGNORECASE | re.DOTALL), "DB_CONNECTION"),
    (re.compile(r"(api[_\-]?key|apikey)\s*[=:]\s*\S+", re.IGNORECASE), "API_KEY"),
    (re.compile(r"(client[_\-]?secret|clientsecret)\s*[=:]\s*\S+", re.IGNORECASE), "CLIENT_SECRET"),
    (re.compile(r"(jwt[_\-]?secret|jwtsecret)\s*[=:]\s*\S+", re.IGNORECASE), "JWT_SECRET"),
    # Base64 heuristik: ≥40 karakter uzunluğu, gerçek base64 karakterleri, = ile biter
    # Neden bu kadar uzun? Kısa base64 dizileri (ör. dosya içerikleri) çok sık geçer;
    # gerçek sırlar genellikle 40+ char uzunluğundadır.
    (re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])", re.IGNORECASE), "BASE64_SECRET"),
]

# Yüksek güvenli pattern sayısı → risk sınırı
_HIGH_CONFIDENCE_RISK_SCORE = 1.0
# Medium pattern başına risk artışı
_MEDIUM_RISK_PER_MATCH = 0.35
# Bu eşiği aşan chunk'lar index'e girmez
SKIP_THRESHOLD = 0.8


@dataclass
class ScanResult:
    redacted_text: str
    risk_score: float
    matches: list[str] = field(default_factory=list)   # eşleşen tip listesi (loglama için)
    should_skip: bool = False


def scan(text: str) -> ScanResult:
    """
    Ham metni tarar:
    1. HIGH_CONFIDENCE pattern → risk_score = 1.0 (anında skip)
    2. MEDIUM_CONFIDENCE pattern → [REDACTED:TYPE] ile değiştir, risk_score += 0.35/match
    3. risk_score > 0.8 → should_skip = True

    Neden HIGH_CONFIDENCE için anında skip?
      Private key veya OpenAI API key, kısmi redaction ile de sızma riski taşır.
      Tüm chunk atlanarak güvenlik sağlanır.
    """
    redacted = text
    risk_score = 0.0
    found_types: list[str] = []

    # 1. Yüksek güvenirlikli tarama
    for pattern, label in _HIGH_CONFIDENCE_PATTERNS:
        if pattern.search(redacted):
            found_types.append(label)
            risk_score = _HIGH_CONFIDENCE_RISK_SCORE
            redacted = pattern.sub(f"[REDACTED:{label}]", redacted)
            logger.warning("SecretScanner: HIGH pattern '%s' bulundu — chunk skip edilecek", label)

    # 2. Orta güvenirlikli tarama (high zaten tetiklendiyse bile redact et)
    for pattern, label in _MEDIUM_CONFIDENCE_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            found_types.append(label)
            count = len(pattern.findall(redacted))
            risk_score = min(1.0, risk_score + count * _MEDIUM_RISK_PER_MATCH)
            redacted = pattern.sub(f"[REDACTED:{label}]", redacted)

    should_skip = risk_score > SKIP_THRESHOLD

    if should_skip:
        logger.warning(
            "SecretScanner: risk_score=%.2f > %.2f — chunk atlandı. Tipler: %s",
            risk_score, SKIP_THRESHOLD, found_types,
        )

    return ScanResult(
        redacted_text=redacted,
        risk_score=risk_score,
        matches=found_types,
        should_skip=should_skip,
    )
