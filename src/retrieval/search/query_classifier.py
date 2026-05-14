"""
Sorgu tipi sınıflandırıcı + Koşullu Query Rewrite kararı.

Refactor değişiklikleri:
  - classify()     : aynı heuristik, aynı tipler (geriye dönük uyumlu)
  - should_rewrite(): Query rewrite KOŞULA BAĞLI — her zaman çalışmaz.

Neden koşullu rewrite?
  "auth refresh flow" → teknik keyword var, rewrite gerekmez.
  "neden login düşüyor" → doğal dil ambiguity var, rewrite gerekir.

Rewrite kriterleri (herhangi biri yeterliyse rewrite yap):
  1. query çok kısa (< 4 token)
  2. teknik keyword YOKSA ve doğal dil sinyali VARSA
  3. top1 retrieval score düşükse (dışarıdan geçirilir)
"""
from __future__ import annotations

import re
from typing import Literal

QueryType = Literal["factual_doc", "code_relation", "config_lookup", "broad_summary"]

# ── Keyword pattern tabloları ────────────────────────────────────────────────
_BROAD_SUMMARY_KEYWORDS = [
    "hepsini anlat", "genel bakış", "genel özet", "özetle", "tüm ",
    "summary", "overview", "list all", "hepsini listele", "tüm kurallar",
]

_CONFIG_LOOKUP_KEYWORDS = [
    "komut", "migration komutu", "dotnet ef", "npm run", "adım ",
    "nasıl kurulur", "setup", "install", "configuration", "appsettings",
    "env ", ".env", "environment variable", "port ", "docker", "dockerfile",
    "script ", "pipeline ", "çalıştır", "run ", "build ", "deploy",
]

_CODE_RELATION_KEYWORDS = [
    "çağırıyor", "bağımlılık", "dependency", "depends on", "implements",
    "extends", "inherits", "kullanıyor", "inject", "injects", "calls",
    "where is used", "nerede kullanılıyor", "callers of", "usages",
    "service that", "class that", "handler for", "repository of",
    "nasıl çalışıyor", "how does", "akış", "flow",
]

_FACTUAL_DOC_KEYWORDS = [
    "nedir", "nasıl", "neden", "kuralı", "kurallar", "yasak", "zorunlu",
    "what is", "why is", "how to", "rule", "policy", "guideline",
    "saklanır", "kaydedilir", "şifrele", "hash", "minimum", "maksimum",
    "tanımı", "definition", "should", "must", "forbidden", "required",
]

# Teknik keyword varlığı — bunlar varsa rewrite büyük ihtimal gerekmez
_TECHNICAL_KEYWORDS = [
    r"\b[A-Z][a-zA-Z]+(?:Service|Controller|Repository|Handler|Middleware|Store|Manager)\b",
    r"\b(?:jwt|oauth|dto|api|http|sql|redis|qdrant|neo4j|grpc|rest|graphql)\b",
    r"\b(?:async|await|inject|interface|abstract|override|virtual)\b",
    r"\b[A-Za-z]+(?:Exception|Error|Result|Response|Request)\b",
]

# Doğal dil ambiguity sinyalleri — bunlar varsa rewrite yardımcı olabilir
_AMBIGUITY_SIGNALS = [
    r"\bneden\b", r"\bnasıl\b", r"\bniçin\b", r"\bgidiyor\b", r"\bdüşüyor\b",
    r"\bçalışmıyor\b", r"\bwhy\b", r"\bhow come\b", r"\bwhat happens\b",
]

_MIN_TECHNICAL_TOKENS = 4   # Bu uzunluğun altındaki sorgular "kısa" kabul edilir


def classify(query: str) -> QueryType:
    """Sorgu tipini heuristik keyword eşleşmesiyle belirler."""
    q = query.lower().strip()
    if _matches_any(q, _BROAD_SUMMARY_KEYWORDS):
        return "broad_summary"
    if _matches_any(q, _CONFIG_LOOKUP_KEYWORDS):
        return "config_lookup"
    if _matches_any(q, _CODE_RELATION_KEYWORDS):
        return "code_relation"
    return "factual_doc"


def should_rewrite(query: str, top1_score: float = 1.0) -> bool:
    """
    Query rewrite yapılmalı mı?

    True döndüren durumlar:
      1. Sorgu çok kısaysa (< MIN_TECHNICAL_TOKENS token)
      2. Top1 retrieval skoru düşükse (< 0.40)
      3. Teknik keyword YOK + doğal dil ambiguity sinyali VAR

    False döndüren durumlar (rewrite gerekmez):
      - Sorgu teknik terimler içeriyorsa
      - Sorgu yeterince uzun ve açıksa
    """
    tokens = re.findall(r"\S+", query.strip())

    # Kural 1: Çok kısa sorgu
    if len(tokens) < _MIN_TECHNICAL_TOKENS:
        return True

    # Kural 2: Düşük retrieval skoru — retrieval zaten kötü gidiyorsa rewrite dene
    if top1_score < 0.40:
        return True

    # Kural 3: Teknik keyword YOK mu?
    has_technical = any(
        re.search(pattern, query, re.IGNORECASE)
        for pattern in _TECHNICAL_KEYWORDS
    )
    if has_technical:
        return False   # Teknik keyword var → rewrite gerekmez

    # Doğal dil ambiguity var mı?
    has_ambiguity = any(
        re.search(sig, query, re.IGNORECASE)
        for sig in _AMBIGUITY_SIGNALS
    )
    return has_ambiguity


def _matches_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


# ── Tip bazlı top_k önerileri ────────────────────────────────────────────────
TOP_K_BY_TYPE: dict[QueryType, int] = {
    "factual_doc":   8,
    "code_relation": 10,
    "config_lookup": 5,
    "broad_summary": 12,
}
