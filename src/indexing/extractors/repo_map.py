"""
Repository Map — Projenin Yüksek Seviye Semantik Haritası.

Claude Code / Cursor benzeri sistemlerin gücünün büyük bölümü burada:
  Her module/class için önceden bilinen bir navigasyon haritası.

Örnek çıktı:
  {
    "AuthModule": {
      "depends_on": ["UserModule", "JwtModule"],
      "entrypoints": ["AuthController"],
      "core_services": ["AuthService", "RefreshTokenService"],
      "file_count": 5,
      "path": "src/auth/"
    }
  }

Kullanım:
  1. İndeksleme sırasında build_repo_map() çağrılır → Redis'e yazılır.
  2. Broad/architecture sorguları önce get_repo_map() ile haritayı okur.
  3. Haritaya göre hedefli retrieval yapılır (fallback: normal HybridRetrieval).

Neden Redis (TTL + invalidation)?
  - 24 saat TTL yeterlidir; her yeni indeksleme haritayı yeniler.
  - key: repo_map:{collection}:{index_sha} → stale map sorunu ortadan kalkar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.redis_store import RedisStore
    from src.storage.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)

_MAP_TTL_SECONDS = int(os.getenv("REPO_MAP_TTL", str(24 * 3600)))  # 24 saat
_MAX_MODULES = int(os.getenv("REPO_MAP_MAX_MODULES", "200"))        # Çok büyük repo'larda sınır


def _map_redis_key(collection: str, index_version: str) -> str:
    """
    Redis key'i: collection + index versiyonu ile benzersiz.
    index_version tipik olarak son commit SHA veya indeksleme hash'i.
    """
    version_hash = hashlib.sha256(index_version.encode()).hexdigest()[:12]
    return f"repo_map:{collection}:{version_hash}"


async def build_repo_map(
    collection: str,
    neo4j: "Neo4jStore",
    redis: "RedisStore",
    index_version: str = "default",
) -> dict:
    """
    Neo4j'deki graf verilerinden repository haritası oluşturur.
    Sonucu Redis'e yazar (TTL: REPO_MAP_TTL saniye).

    Dönen dict: {module_name: {depends_on, entrypoints, core_services, file_count, path}}
    """
    repo_map: dict[str, dict] = {}

    try:
        # Neo4j'de modül bağımlılıklarını sorgula
        cypher_modules = """
        MATCH (m:Module {collection: $collection})
        OPTIONAL MATCH (m)-[:DEPENDS_ON]->(dep:Module)
        OPTIONAL MATCH (m)-[:CONTAINS]->(cls:Class)
        OPTIONAL MATCH (cls)-[:OWNS]->(fn:Function)
        RETURN
            m.name AS module_name,
            m.path AS module_path,
            m.file_count AS file_count,
            collect(DISTINCT dep.name) AS depends_on,
            [cls2 IN collect(DISTINCT cls) WHERE cls2.name ENDS WITH 'Controller' | cls2.name] AS entrypoints,
            [fn2 IN collect(DISTINCT fn) WHERE fn2.is_public = true | fn2.name][..5] AS core_services
        ORDER BY m.name
        LIMIT $limit
        """
        records = await neo4j.query(
            cypher_modules,
            {"collection": collection, "limit": _MAX_MODULES},
        )

        for rec in records:
            module_name = rec.get("module_name") or "Unknown"
            repo_map[module_name] = {
                "depends_on": [d for d in (rec.get("depends_on") or []) if d],
                "entrypoints": [e for e in (rec.get("entrypoints") or []) if e],
                "core_services": [s for s in (rec.get("core_services") or []) if s],
                "file_count": rec.get("file_count") or 0,
                "path": rec.get("module_path") or "",
            }

    except Exception as exc:
        logger.warning("Neo4j repo map sorgusu başarısız: %s. Boş map kullanılıyor.", exc)
        return {}

    if not repo_map:
        logger.info("Repo map boş döndü (collection=%s, henüz indekslenmemiş olabilir).", collection)
        return {}

    # Redis'e yaz
    try:
        redis_key = _map_redis_key(collection, index_version)
        await redis.set_raw(redis_key, json.dumps(repo_map), ttl=_MAP_TTL_SECONDS)
        logger.info(
            "Repo map yazıldı: %d modül, collection=%s, ttl=%ds",
            len(repo_map), collection, _MAP_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning("Repo map Redis yazma hatası: %s", exc)

    return repo_map


async def get_repo_map(
    collection: str,
    redis: "RedisStore",
    index_version: str = "default",
) -> dict | None:
    """
    Redis'ten repo haritasını okur.
    Bulamazsa None döner → caller normal retrieval'a devam eder.
    """
    try:
        redis_key = _map_redis_key(collection, index_version)
        raw = await redis.get_raw(redis_key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Repo map Redis okuma hatası: %s", exc)
    return None


def find_relevant_modules(query: str, repo_map: dict, top_n: int = 5) -> list[str]:
    """
    Sorguya göre repo haritasından ilgili modülleri döner.
    Basit keyword overlap (büyük harf duyarsız).

    Bu fonksiyon HybridSearch öncesi çağrılır; belirlenen modüllerin
    dosya path'leri retrieval filter olarak kullanılabilir.
    """
    query_lower = query.lower()
    query_tokens = set(query_lower.split())

    scored: list[tuple[float, str]] = []
    for module_name, info in repo_map.items():
        name_lower = module_name.lower()
        path_lower = (info.get("path") or "").lower()
        # Modül adı ve path'te token overlap
        all_text = f"{name_lower} {path_lower} " + " ".join(
            (info.get("core_services") or []) + (info.get("entrypoints") or [])
        ).lower()
        all_tokens = set(all_text.split())
        overlap = len(query_tokens & all_tokens) / max(len(query_tokens), 1)
        if overlap > 0:
            scored.append((overlap, module_name))

    scored.sort(reverse=True)
    return [name for _, name in scored[:top_n]]
