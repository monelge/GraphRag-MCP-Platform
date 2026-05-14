from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.agent.orchestrator.checkpoints import CheckpointStore
from src.agent.tasks.task_store import TaskStore
from src.control.evals.dataset_manager import DatasetManager
from src.control.models.gateway import ModelGateway
from src.control.observability.tracer import PipelineTracer
from src.execution.runners.command_runner import CommandRunner
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager
from src.retrieval.context.token_budget import TokenBudgetOptimizer
from src.retrieval.ranking.deduplicator import SemanticDeduplicator
from src.retrieval.ranking.reranker import LocalReranker
from src.retrieval.search.impact_analysis import ImpactAnalyzer
from src.shared.project_registry import ProjectRegistry
from src.storage.episodic_store import EpisodicStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.postgres_store import PostgresStore
from src.storage.redis_store import RedisStore

if TYPE_CHECKING:
    from src.agent.orchestrator.state_machine import TaskOrchestrator


@dataclass(frozen=True)
class AppContext:
    """Handler ve node katmanının paylaştığı bağımlılık konteyneri."""

    redis: RedisStore
    postgres: PostgresStore
    neo4j: Neo4jStore
    episodic: EpisodicStore
    registry: ProjectRegistry
    task_store: TaskStore
    orchestrator: "TaskOrchestrator"
    command_runner: CommandRunner
    runtime_manager: SandboxRuntimeManager
    model_gateway: ModelGateway
    dataset_manager: DatasetManager
    reranker: LocalReranker
    deduplicator: SemanticDeduplicator
    budget_optimizer: TokenBudgetOptimizer
    impact_analyzer: ImpactAnalyzer
    tracer: type[PipelineTracer]
    checkpoint_store: Optional[CheckpointStore] = None
    retrieval_handler: Optional[object] = None
