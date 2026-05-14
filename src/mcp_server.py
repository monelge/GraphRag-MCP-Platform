from __future__ import annotations
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from src.shared.logging_config import setup_logging, get_logger

# Logging en erken kurulur — diğer import'lardan önce
setup_logging()
logger = get_logger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    class _FallbackToolManager:
        def __init__(self):
            self._tools = {}

    class FastMCP:
        """mcp paketi yoksa testler için minimal FastMCP uyumluluğu sağlar."""

        def __init__(self, name: str, lifespan=None):
            self.name = name
            self.lifespan = lifespan
            self._tool_manager = _FallbackToolManager()

        @property
        def tools(self):
            return self._tool_manager._tools

        def tool(self):
            def decorator(func):
                self._tool_manager._tools[func.__name__] = func
                return func

            return decorator

        def run(self, transport: str = "stdio"):
            return None

from src.agent.orchestrator.state_machine import TaskOrchestrator
from src.agent.tasks.task_store import TaskStore
from src.control.evals.dataset_manager import DatasetManager
from src.control.models.gateway import ModelGateway
from src.control.observability.tracer import PipelineTracer
from src.execution.runners.command_runner import CommandRunner
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager
from src.handlers import (
    AppContext,
    ControlHandler,
    ExecutionHandler,
    IndexingHandler,
    MemoryHandler,
    RetrievalHandler,
)
from src.retrieval.context.token_budget import TokenBudgetOptimizer
from src.retrieval.ranking.deduplicator import SemanticDeduplicator
from src.retrieval.ranking.reranker import LocalReranker
from src.retrieval.search.impact_analysis import ImpactAnalyzer
from src.shared.project_registry import ProjectRegistry
from src.storage.episodic_store import EpisodicStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.postgres_store import PostgresStore
from src.storage.redis_store import RedisStore

load_dotenv()

_redis = RedisStore()
_postgres = PostgresStore()
_neo4j = Neo4jStore()
_episodic = EpisodicStore()
_registry = ProjectRegistry()
_task_store = TaskStore(_postgres)
_orchestrator = TaskOrchestrator(_task_store)
_command_runner = CommandRunner()
_runtime_manager = SandboxRuntimeManager(_command_runner)
_model_gateway = ModelGateway()
_dataset_manager = DatasetManager()
_reranker = LocalReranker()
_deduplicator = SemanticDeduplicator()
_budget_opt = TokenBudgetOptimizer()
_impact_analyzer = ImpactAnalyzer(_neo4j)
_tracer = PipelineTracer

_app_ctx = AppContext(
    redis=_redis,
    postgres=_postgres,
    neo4j=_neo4j,
    episodic=_episodic,
    registry=_registry,
    task_store=_task_store,
    orchestrator=_orchestrator,
    command_runner=_command_runner,
    runtime_manager=_runtime_manager,
    model_gateway=_model_gateway,
    dataset_manager=_dataset_manager,
    reranker=_reranker,
    deduplicator=_deduplicator,
    budget_optimizer=_budget_opt,
    impact_analyzer=_impact_analyzer,
    tracer=_tracer,
)

_indexing = IndexingHandler(_app_ctx)
_retrieval = RetrievalHandler(_app_ctx)
_memory = MemoryHandler(_app_ctx)
_execution = ExecutionHandler(_app_ctx, retrieval=_retrieval)
_control = ControlHandler(_app_ctx, indexing=_indexing)
_execution.register_default_handlers()


@asynccontextmanager
async def _lifespan(server):
    """Shared servis bağlantılarını açıp kapatır."""
    logger.info("MCP server başlatılıyor", extra={"server": "graph-mcp"})
    try:
        await _postgres.connect()
        logger.info("PostgreSQL bağlantısı kuruldu")
        await _neo4j.connect()   # retry + create_constraints içinde
        logger.info("Neo4j bağlantısı kuruldu ve kısıtlamalar uygulandı")
        logger.info("MCP server hazır — tüm servisler çevrimiçi")
    except Exception:
        logger.exception("Servis başlatma hatası — MCP server çalışmayabilir")
        raise
    yield
    logger.info("MCP server kapatılıyor")
    await _redis.close()
    await _postgres.close()
    await _neo4j.close()
    close_episodic = getattr(_episodic, "close", None)
    if callable(close_episodic):
        await close_episodic()
    logger.info("Tüm servis bağlantıları kapatıldı")


app = FastMCP("graph-mcp", lifespan=_lifespan)

import functools
import time as _time

def _tool(func):
    """
    @app.tool() + otomatik çağrı loglama.
    Her MCP tool çağrısında araç adı, koleksiyon (varsa), sorgu (varsa)
    ve süre INFO seviyesinde loglanır; hata olursa ERROR loglanıp yeniden fırlatılır.
    """
    @app.tool()
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        _t0 = _time.monotonic()
        # Logda gösterilecek context bilgilerini topla
        _ctx: dict = {"tool": func.__name__}
        for _k in ("collection", "query", "task_id", "project_path", "title"):
            if _k in kwargs:
                _ctx[_k] = str(kwargs[_k])[:120]
        logger.info("MCP tool çağrıldı", extra=_ctx)
        try:
            result = await func(*args, **kwargs)
            _ctx["duration_ms"] = round((_time.monotonic() - _t0) * 1000)
            logger.info("MCP tool tamamlandı", extra=_ctx)
            return result
        except Exception as _exc:
            _ctx["duration_ms"] = round((_time.monotonic() - _t0) * 1000)
            logger.error("MCP tool hata", extra={**_ctx, "error": str(_exc)})
            raise
    return wrapper


@_tool
async def index_project(project_path: str, collection: str = "", batch_size: int = 32) -> str:
    return await _indexing.index_project(project_path, collection, batch_size)


@_tool
async def incremental_index_project(
    project_path: str,
    changed_files: list[str] | None = None,
    batch_size: int = 32,
) -> str:
    return await _indexing.incremental_index_project(project_path, changed_files, batch_size)


@_tool
async def search_code(
    query: str,
    collection: str = "",
    top_k: int = 0,
    rewrite_query: bool | None = None,
) -> str:
    return await _retrieval.search_code(query, collection, top_k, rewrite_query)


@_tool
async def explain_code(query: str, collection: str = "", top_k: int = 5) -> str:
    return await _retrieval.explain_code(query, collection, top_k)


@_tool
async def index_agent_docs(project_path: str) -> str:
    return await _indexing.index_agent_docs(project_path)


@_tool
async def search_agent_docs(
    query: str,
    collection: str = "",
    layer: str | None = None,
    doc_priority: str | None = None,
) -> str:
    return await _indexing.search_agent_docs(query, collection, layer, doc_priority)


@_tool
async def store_memory(
    title: str,
    content: str,
    memory_type: str = "general",
    tags: list[str] | None = None,
    collection: str = "",
    module: str = "",
    commit_sha: str = "",
    provenance: str = "",
    valid_days: int | None = None,
    status: str = "active",
) -> str:
    return await _memory.store_memory(
        title,
        content,
        memory_type,
        tags,
        collection,
        module,
        commit_sha,
        provenance,
        valid_days,
        status,
    )


@_tool
async def recall_memory(
    query: str,
    memory_type: str | None = None,
    memory_layer: str | None = None,
    collection: str = "",
    include_invalid: bool = False,
    top_k: int = 5,
) -> str:
    return await _memory.recall_memory(
        query,
        memory_type,
        memory_layer,
        collection,
        include_invalid,
        top_k,
    )


@_tool
async def compact_memory(collection: str, query: str = "*") -> str:
    return await _memory.compact_memory(collection, query)


@_tool
async def create_agent_task(
    title: str,
    description: str,
    collection: str,
    steps: list[str] | None = None,
) -> str:
    """
    Yeni ajan görevi başlatır.

    steps (opsiyonel): Adım açıklamalarının listesi — her eleman TaskStep olarak kaydedilir
      ve get_task_status ile takip edilebilir.
    Örnek: steps=["Etki analizi yap", "Endpoint güncelle", "Test yaz"]
    """
    return await _execution.create_agent_task(title, description, collection, steps)


@_tool
async def get_task_status(task_id: str) -> str:
    return await _execution.get_task_status(task_id)


@_tool
async def approve_task_step(task_id: str, feedback: str = "approved") -> str:
    return await _execution.approve_task_step(task_id, feedback)


@_tool
async def complete_task(task_id: str, note: str = "") -> str:
    """Görevi herhangi bir durumdan done'a çeker. Zaten done/aborted olanlara dokunulmaz."""
    return await _execution.complete_task(task_id, note)


@_tool
async def list_agent_tasks(collection: str = "", status: str = "") -> str:
    return await _execution.list_agent_tasks(collection, status)


@_tool
async def run_verification_plan(
    project_path: str,
    run_build: bool = True,
    run_tests: bool = True,
    run_lint: bool = False,
) -> str:
    return await _execution.run_verification_plan(project_path, run_build, run_tests, run_lint)


@_tool
async def run_retrieval_eval(dataset_name: str, collection: str) -> str:
    return await _execution.run_retrieval_eval(dataset_name, collection)


@_tool
async def get_control_plane_stats() -> str:
    return await _control.get_control_plane_stats()


@_tool
async def register_project(
    project_path: str,
    collection: str = "",
    index_code: bool = True,
    index_docs: bool = True,
    batch_size: int = 32,
) -> str:
    return await _control.register_project(project_path, collection, index_code, index_docs, batch_size)


@_tool
async def list_projects() -> str:
    return await _control.list_projects()


@_tool
async def summarize_repository(project_path: str, collection: str = "") -> str:
    return await _control.summarize_repository(project_path, collection)


@_tool
async def search_repo_architecture(query: str, collection: str = "", top_k: int = 6) -> str:
    return await _retrieval.search_repo_architecture(query, collection, top_k)


@_tool
async def analyze_change_impact(
    project_path: str,
    changed_paths: list[str],
    collection: str = "",
) -> str:
    return await _control.analyze_change_impact(project_path, changed_paths, collection)


@_tool
async def store_decision_memory(
    title: str,
    content: str,
    collection: str,
    module: str = "",
    commit_sha: str = "",
    provenance: str = "",
    tags: list[str] | None = None,
) -> str:
    return await _memory.store_decision_memory(
        title,
        content,
        collection,
        module,
        commit_sha,
        provenance,
        tags,
    )


@_tool
async def search_decisions(query: str, collection: str = "", top_k: int = 5) -> str:
    return await _memory.search_decisions(query, collection, top_k)


if __name__ == "__main__":
    app.run(transport="stdio")
