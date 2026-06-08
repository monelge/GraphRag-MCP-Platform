"""
ARQ Task Worker — periyodik arka plan görevleri.

Görevler:
  - periodic_workspace_gc : stale workspace temizliği (saatte bir)
  - periodic_session_gc   : süresi dolmuş Redis session temizliği
  - periodic_memory_cycle : koleksiyon belleği sıkıştırma (günde bir)

ARQ Redis broker olarak kullanır — ek bağımlılık gerekmez.

Başlatma:
  arq src.agent.task_worker.WorkerSettings
"""

from __future__ import annotations

import os
from typing import Any

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ── Periyotlar ────────────────────────────────────────────────────────────────
GC_INTERVAL_S:     int = int(os.getenv("WORKER_GC_INTERVAL_S",     "3600"))   # 1 saat
SESSION_GC_S:      int = int(os.getenv("WORKER_SESSION_GC_S",      "3600"))   # 1 saat
MEMORY_CYCLE_S:    int = int(os.getenv("WORKER_MEMORY_CYCLE_S",    "86400"))  # 1 gün
DEFAULT_COLLECTION: str = os.getenv("DEFAULT_COLLECTION", "WareLogisticcBYS").lower()


# ── Görev fonksiyonları ───────────────────────────────────────────────────────

async def periodic_workspace_gc(ctx: dict) -> dict:
    """
    Stale workspace dizinlerini ve eski snapshot tag'lerini temizler.
    Aktif (RUNNING/SUSPENDED) görev listesini PostgreSQL'den alır.
    """
    pg   = ctx.get("postgres")
    from src.agent.workspace_manager import get_workspace_manager
    from src.agent.state_machine import AgentStateMachine

    sm   = AgentStateMachine(pg, ctx.get("redis"))
    wm   = get_workspace_manager()

    try:
        active = await sm.get_active_task_ids()
        removed = await wm.prune_stale_workspaces(active_task_ids=active)

        # Kayıtlı projelerde snapshot GC
        snapshot_removed = 0
        project_paths = _get_known_projects(pg)
        for path in project_paths:
            snapshot_removed += await wm.prune_snapshots(path)

        logger.info(
            "GC tamamlandı: %d workspace, %d snapshot temizlendi",
            removed, snapshot_removed,
        )
        return {"workspaces_removed": removed, "snapshots_removed": snapshot_removed}
    except Exception as exc:
        logger.warning("periodic_workspace_gc hatası: %s", exc)
        return {"error": str(exc)}


async def periodic_session_gc(ctx: dict) -> dict:
    """
    Süresi dolmuş agent:session:* ve agent:checkpoint:* anahtarlarını temizler.
    Redis TTL otomatik siler; bu görev sadece sahipsiz anahtarları kontrol eder.
    """
    redis = ctx.get("redis")
    if redis is None:
        return {"skipped": "redis yok"}

    cleaned = 0
    try:
        # Orphaned checkpoint'leri bul: Redis'te var ama PG'de task tamamlanmış
        pg = ctx.get("postgres")
        if pg is None:
            return {"skipped": "postgres yok"}

        from src.agent.state_machine import AgentStateMachine
        sm = AgentStateMachine(pg, redis)

        # Tamamlanmış/başarısız task_id'leri Redis'ten temizle
        pool = getattr(pg, "_pool", None)
        if pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT task_id FROM agent_tasks WHERE status IN ('COMPLETED','FAILED','CANCELLED')"
                    " AND updated_at < NOW() - INTERVAL '2 hours'"
                )
            for row in rows:
                await sm.delete(row["task_id"])
                cleaned += 1

        logger.info("Session GC: %d tamamlanmış görev Redis'ten temizlendi", cleaned)
        return {"cleaned": cleaned}
    except Exception as exc:
        logger.warning("periodic_session_gc hatası: %s", exc)
        return {"error": str(exc)}


async def periodic_memory_cycle(ctx: dict) -> dict:
    """
    Varsayılan koleksiyonda bellek sıkıştırma döngüsü çalıştırır.
    """
    try:
        from src.mcp.tool_registry import compact_memory
        result = await compact_memory(collection=DEFAULT_COLLECTION)
        logger.info("Bellek döngüsü tamamlandı: %s", str(result)[:100])
        return {"status": "ok", "collection": DEFAULT_COLLECTION}
    except Exception as exc:
        logger.warning("periodic_memory_cycle hatası: %s", exc)
        return {"error": str(exc)}


# ── Worker başlangıç / kapanış ─────────────────────────────────────────────────

async def startup(ctx: dict) -> None:
    """ARQ worker başladığında çağrılır — storage bağlantılarını kur."""
    pg_dsn    = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    redis_url = os.getenv("REDIS_URL")

    if pg_dsn:
        try:
            from src.storage.postgres_store import PostgresStore
            pg = PostgresStore(pg_dsn)
            await pg.connect()
            ctx["postgres"] = pg
            logger.info("Worker: PostgreSQL bağlandı")
        except Exception as exc:
            logger.warning("Worker: PostgreSQL bağlantı hatası: %s", exc)

    if redis_url:
        try:
            from src.storage.redis_store import RedisStore
            r = RedisStore(redis_url)
            await r.connect()
            ctx["redis"] = r
            logger.info("Worker: Redis bağlandı")
        except Exception as exc:
            logger.warning("Worker: Redis bağlantı hatası: %s", exc)

    logger.info("ARQ Worker hazır")


async def shutdown(ctx: dict) -> None:
    """ARQ worker kapanırken çağrılır."""
    pg = ctx.get("postgres")
    if pg:
        try:
            await pg.close()
        except Exception:
            pass
    logger.info("ARQ Worker kapatıldı")


# ── ARQ WorkerSettings ────────────────────────────────────────────────────────

class WorkerSettings:
    """ARQ'nun beklediği ayar sınıfı."""

    redis_settings = None   # startup'ta atanır

    functions = [
        periodic_workspace_gc,
        periodic_session_gc,
        periodic_memory_cycle,
    ]

    cron_jobs = []   # cron_jobs aşağıda doldurulur

    on_startup  = startup
    on_shutdown = shutdown

    # Periyodik çalışma planı — cron syntax
    @classmethod
    def _build_cron(cls):
        try:
            from arq.cron import cron
            cls.cron_jobs = [
                cron(periodic_workspace_gc, hour=None, minute=0),   # her saat başı
                cron(periodic_session_gc,   hour=None, minute=30),  # her saat 30
                cron(periodic_memory_cycle, hour=3,    minute=0),   # her gün 03:00
            ]
        except ImportError:
            logger.warning("arq kütüphanesi yok — cron jobs devre dışı")

    @classmethod
    def _set_redis(cls):
        try:
            from arq.connections import RedisSettings as ArqRedis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            cls.redis_settings = ArqRedis.from_dsn(redis_url)
        except ImportError:
            pass

    max_jobs             = int(os.getenv("WORKER_MAX_JOBS", "4"))
    job_timeout          = int(os.getenv("WORKER_JOB_TIMEOUT_S", "300"))
    health_check_interval= int(os.getenv("WORKER_HEALTH_CHECK_S", "30"))
    keep_result          = int(os.getenv("WORKER_KEEP_RESULT_S", "3600"))


# Sınıf hazırlığı
WorkerSettings._build_cron()
WorkerSettings._set_redis()


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _get_known_projects(pg) -> list[str]:
    """
    PostgreSQL'den proje yollarını senkron olarak alamayız;
    kayıtlı projeleri JSON dosyasından oku.
    """
    registry_path = os.getenv("PROJECT_REGISTRY_PATH", "/app/data/project_registry.json")
    try:
        import json
        with open(registry_path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p.get("path", "") for p in data if p.get("path")]
        if isinstance(data, dict):
            return [p.get("path", "") for p in data.values() if isinstance(p, dict) and p.get("path")]
    except Exception:
        pass
    return []
