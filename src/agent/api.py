"""
Agent API — Port 8001 FastAPI uygulaması.

Endpointler:
  POST /v1/agent/run          — Yeni TDAD görevi başlat (SSE akışı)
  POST /v1/agent/approve      — HITL onay gönder
  GET  /v1/agent/status/{id}  — Görev durumu
  GET  /v1/agent/tasks        — Görev listesi
  GET  /v1/health             — Sağlık kontrolü

Lifespan: başlangıçta DB schema uygular; kapanışta GC çalıştırır.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agent.codeact_runner import RunConfig, StepEvent, build_runner
from src.agent.state_machine import AGENT_SCHEMA_SQL, AgentStateMachine
from src.agent.workspace_manager import get_workspace_manager
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ── Global kaynaklar ──────────────────────────────────────────────────────────
_postgres: Any = None
_redis:    Any = None
_llm:      Any = None
_mcp:      Any = None

# task_id → asyncio.Queue (HITL onayları)
_approval_queues: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlangıç/kapanış yöneticisi."""
    global _postgres, _redis, _llm, _mcp

    # Depolama katmanlarını başlat
    await _init_storage()

    # DB schema migration — asyncpg pool üzerinden
    if _postgres:
        pool = getattr(_postgres, "_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    # IF NOT EXISTS ile çalıştır; duplicate hatalarını yoksay
                    async with conn.transaction():
                        for stmt in AGENT_SCHEMA_SQL.strip().split(";"):
                            stmt = stmt.strip()
                            if stmt:
                                try:
                                    await conn.execute(stmt)
                                except Exception:
                                    pass  # IF NOT EXISTS dışı race → görmezden gel
                logger.info("Agent DB schema uygulandı")
            except Exception as exc:
                logger.debug("DB schema uygulama hatası: %s", exc)

    logger.info("Agent API hazır — port 8001")
    yield

    # Kapanışta GC
    if _postgres:
        sm = AgentStateMachine(_postgres, _redis)
        active = await sm.get_active_task_ids()
        removed = await get_workspace_manager().prune_stale_workspaces(active)
        logger.info("GC: %d stale workspace temizlendi", removed)

    logger.info("Agent API kapatılıyor")


async def _init_storage() -> None:
    """PostgreSQL ve Redis bağlantılarını başlat."""
    global _postgres, _redis, _llm, _mcp

    pg_dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    redis_url = os.getenv("REDIS_URL")

    if pg_dsn:
        try:
            from src.storage.postgres_store import PostgresStore
            _postgres = PostgresStore(pg_dsn)
            await _postgres.connect()
            logger.info("PostgreSQL bağlandı")
        except Exception as exc:
            logger.warning("PostgreSQL bağlantı hatası: %s", exc)

    if redis_url:
        try:
            from src.storage.redis_store import RedisStore
            _redis = RedisStore(redis_url)
            await _redis.connect()
            logger.info("Redis bağlandı: available=%s", _redis.available)
        except Exception as exc:
            logger.warning("Redis bağlantı hatası: %s", exc)

    # LLM client
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            from src.agent.llm_client import LLMClient
            _llm = LLMClient(api_key=openrouter_key)
        except ImportError:
            pass

    # MCP handler (self)
    try:
        from src.agent.mcp_bridge import MCPBridge
        _mcp = MCPBridge()
    except ImportError:
        pass


# ── Request modelleri (modül seviyesinde — Pydantic forward ref sorunu olmaz) ──

class RunRequest(BaseModel):
    goal:          str            = Field(..., min_length=3)
    collection:    str            = Field(default="warelogisticcbys")
    project_path:  str            = Field(default="/app")
    hitl_enabled:  bool           = Field(default=True)
    tier_override: Optional[str]  = Field(default=None)


class ApproveRequest(BaseModel):
    task_id:  str
    approved: bool = True


def create_app() -> FastAPI:
    app = FastAPI(
        title="GraphRagMCP Agent API",
        version="1.0.0",
        description="TDAD (Test-Driven Agentic Development) orchestration API",
        lifespan=lifespan,
    )

    # ── Sağlık kontrolü ──────────────────────────────────────────────────

    @app.get("/v1/health")
    async def health():
        return {
            "status": "ok",
            "postgres": _postgres is not None,
            "redis":    _redis    is not None,
            "llm":      _llm      is not None,
            "mcp":      _mcp      is not None,
            "ts":       time.time(),
        }

    # ── Görev başlatma — SSE akışı ────────────────────────────────────────

    @app.post("/v1/agent/run")
    async def run_agent(req: RunRequest):
        task_id = str(uuid.uuid4())
        q: asyncio.Queue = asyncio.Queue()
        _approval_queues[task_id] = q

        config = RunConfig(
            task_id=task_id,
            goal=req.goal,
            collection=req.collection.lower(),
            project_path=req.project_path,
            hitl_enabled=req.hitl_enabled,
            tier_override=req.tier_override,
        )
        runner = build_runner(_postgres, _redis, _llm, _mcp, q)

        async def event_stream():
            # task_id'yi hemen yayınla
            yield _sse({"event": "task_created", "task_id": task_id})
            try:
                async for event in runner.run(config):
                    yield _sse(_event_dict(event))
                    if event.step in ("DONE", "FAILED"):
                        break
            except Exception as exc:
                logger.exception("SSE stream hatası: %s", exc)
                yield _sse({"event": "error", "message": str(exc)})
            finally:
                _approval_queues.pop(task_id, None)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "X-Accel-Buffering":"no",
                "X-Task-Id":        task_id,
            },
        )

    # ── HITL Onay ────────────────────────────────────────────────────────

    @app.post("/v1/agent/approve")
    async def approve(req: ApproveRequest):
        q = _approval_queues.get(req.task_id)
        if q is None:
            raise HTTPException(404, f"Görev bulunamadı veya onay beklemiyor: {req.task_id}")
        await q.put(req.approved)
        return {"task_id": req.task_id, "approved": req.approved, "status": "queued"}

    # ── Görev durumu ──────────────────────────────────────────────────────

    @app.get("/v1/agent/status/{task_id}")
    async def task_status(task_id: str):
        if not _postgres:
            raise HTTPException(503, "PostgreSQL bağlı değil")
        sm = AgentStateMachine(_postgres, _redis)
        cp = await sm.load(task_id)
        if not cp:
            raise HTTPException(404, f"Görev bulunamadı: {task_id}")
        return {
            "task_id":   cp.task_id,
            "step":      cp.step,
            "tier":      cp.current_tier,
            "model":     cp.selected_model,
            "reflection":cp.reflection_count,
            "tokens":    cp.tokens_used,
            "branch":    cp.current_branch,
            "goal":      cp.goal,
        }

    # ── Görev listesi ─────────────────────────────────────────────────────

    @app.get("/v1/agent/tasks")
    async def list_tasks(
        collection: str = Query(default="warelogisticcbys"),
        limit:      int = Query(default=20, le=100),
    ):
        if not _postgres:
            return {"tasks": [], "warning": "PostgreSQL bağlı değil"}
        sm = AgentStateMachine(_postgres, _redis)
        tasks = await sm.get_task_history(collection.lower(), limit)
        return {"tasks": tasks, "count": len(tasks)}

    # ── Eski MCP endpoint uyumluluğu ──────────────────────────────────────
    # /agent/tasks ← eski client'lar için alias
    @app.get("/agent/tasks")
    async def list_tasks_compat(
        collection: str = Query(default="warelogisticcbys"),
    ):
        return await list_tasks(collection, 20)

    return app


# ── Yardımcılar ──────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _event_dict(event: StepEvent) -> dict:
    return {
        "event":   event.step,
        "status":  event.status,
        "message": event.message,
        **event.data,
    }


# ── Uygulama nesnesi ──────────────────────────────────────────────────────────
app = create_app()
