from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv

from src.agent.orchestrator.checkpoints import CheckpointStore
from src.agent.orchestrator.state_machine import TaskOrchestrator
from src.agent.tasks.task_store import TaskStore
from src.control.evals.dataset_manager import DatasetManager
from src.control.models.budgets import BudgetManager
from src.control.models.gateway import ModelGateway
from src.control.observability.audit import AuditLogger
from src.control.observability.metrics import get_metrics
from src.control.observability.tracer import PipelineTracer
from src.execution.runners.command_runner import CommandRunner
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager
from src.handlers import AppContext, AnalysisHandler, ControlHandler, ExecutionHandler, IndexingHandler, MemoryHandler, RetrievalHandler, OrchestrationHandler
from src.mcp.tool_registry import register_all_tools
from src.retrieval.context.token_budget import TokenBudgetOptimizer
from src.retrieval.ranking.deduplicator import SemanticDeduplicator
from src.retrieval.ranking.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.search.impact_analysis import ImpactAnalyzer
from src.shared.logging_config import get_logger, setup_logging
from src.shared.project_registry import ProjectRegistry
from src.shared.telemetry import setup_telemetry
from src.shared import metrics as prom_metrics
from src.storage.episodic_store import EpisodicStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.postgres_store import PostgresStore
from src.storage.redis_store import RedisStore

setup_logging()
logger = get_logger(__name__)
load_dotenv()
setup_telemetry()

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    class _FallbackToolManager:
        def __init__(self):
            self._tools = {}

    class FastMCP:
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


_redis = RedisStore()
_postgres = PostgresStore()
_neo4j = Neo4jStore()
_episodic = EpisodicStore()
_registry = ProjectRegistry()
_task_store = TaskStore(_postgres)
_checkpoint_store = CheckpointStore(_postgres)
_orchestrator = TaskOrchestrator(_task_store, episodic_store=_episodic, checkpoint_store=_checkpoint_store)
_command_runner = CommandRunner()
_runtime_manager = SandboxRuntimeManager(_command_runner)
_model_gateway = ModelGateway()
_audit = AuditLogger()
_metrics = get_metrics()
_budget_manager = BudgetManager()
_model_gateway.set_postgres(_postgres)
_model_gateway.set_budget_manager(_budget_manager)
# _audit._pg lifespan beklemeden hemen bağlanır; pool yokken log_audit_event zaten erken döner.
_audit.set_postgres(_postgres)
_dataset_manager = DatasetManager()
_reranker = CrossEncoderReranker()
_deduplicator = SemanticDeduplicator()
_budget_opt = TokenBudgetOptimizer()
_impact_analyzer = ImpactAnalyzer(_neo4j)
# PipelineTracer sınıfı (instance deil); retrieval_handler.py içinde ctx.tracer(query=..., ...) ile yeni instance üretilir
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
    checkpoint_store=_checkpoint_store,
    audit_logger=_audit,
    metrics=_metrics,
    budget_manager=_budget_manager,
)

_indexing = IndexingHandler(_app_ctx)
_retrieval = RetrievalHandler(_app_ctx)
_memory = MemoryHandler(_app_ctx)
_execution = ExecutionHandler(_app_ctx, retrieval=_retrieval)
_control = ControlHandler(_app_ctx, indexing=_indexing)
_orchestration = OrchestrationHandler(_app_ctx)
_analysis = AnalysisHandler(_app_ctx)

object.__setattr__(_app_ctx, "retrieval_handler", _retrieval)
object.__setattr__(_app_ctx, "indexing_handler", _indexing)
object.__setattr__(_app_ctx, "memory_handler", _memory)
object.__setattr__(_app_ctx, "execution_handler", _execution)
object.__setattr__(_app_ctx, "control_handler", _control)
object.__setattr__(_app_ctx, "orchestration_handler", _orchestration)
object.__setattr__(_app_ctx, "analysis_handler", _analysis)
_orchestrator.app_context = _app_ctx


@asynccontextmanager
async def _lifespan(server):
    logger.info("MCP server başlatılıyor", extra={"server": "graph-mcp"})
    await _redis.connect()
    await _postgres.connect()
    await _neo4j.connect()
    try:
        yield
    finally:
        await _redis.close()
        await _postgres.close()
        await _neo4j.close()
        close_episodic = getattr(_episodic, "close", None)
        if callable(close_episodic):
            await close_episodic()


def build_app(ctx: AppContext) -> FastMCP:
    from src.shared.config import config
    app = FastMCP("graph-mcp", lifespan=_lifespan)
    register_all_tools(app, ctx)

    # /metrics endpoint — Prometheus scraping için (sadece HTTP/SSE transport'ta anlamlı)
    if config.prometheus_enabled:
        try:
            from fastapi import FastAPI, Response
            from fastapi.routing import APIRoute

            # FastMCP'nin underlying ASGI app'ini al veya wrap et
            underlying = getattr(app, "_app", None) or getattr(app, "app", None)
            if underlying is not None:
                @underlying.get("/metrics", include_in_schema=False)
                async def metrics_endpoint():
                    data, content_type = prom_metrics.generate_metrics_response()
                    return Response(content=data, media_type=content_type)
                logger.info("/metrics endpoint aktif")
        except Exception as e:
            logger.debug("/metrics endpoint eklenemedi: %s", e)

    return app


app = build_app(_app_ctx)
