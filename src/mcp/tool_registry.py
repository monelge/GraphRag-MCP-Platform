"""MCP tool kayıtları ve facade wrapper fonksiyonları."""

from __future__ import annotations

import functools
import time as _time
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)
_app = None
_ctx = None
_indexing = None
_retrieval = None
_memory = None
_execution = None
_control = None


def _tool(func):
    @ _app.tool()
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        started = _time.monotonic()
        log_ctx = {"tool": func.__name__}
        for key in ("collection", "query", "task_id", "project_path", "title"):
            if key in kwargs:
                log_ctx[key] = str(kwargs[key])[:120]
        logger.info("MCP tool çağrıldı", extra=log_ctx)
        try:
            result = await func(*args, **kwargs)
            log_ctx["duration_ms"] = round((_time.monotonic() - started) * 1000)
            logger.info("MCP tool tamamlandı", extra=log_ctx)
            return result
        except Exception as exc:
            log_ctx["duration_ms"] = round((_time.monotonic() - started) * 1000)
            logger.error("MCP tool hata", extra=dict(log_ctx, error=str(exc)))
            raise
    return wrapper


def set_runtime(app, ctx, indexing, retrieval, memory, execution, control) -> None:
    global _app, _ctx, _indexing, _retrieval, _memory, _execution, _control
    _app = app
    _ctx = ctx
    _indexing = indexing
    _retrieval = retrieval
    _memory = memory
    _execution = execution
    _control = control


def register_all_tools(app, ctx) -> None:
    set_runtime(app, ctx, ctx.indexing_handler, ctx.retrieval_handler, ctx.memory_handler, ctx.execution_handler, ctx.control_handler)
    for func in TOOL_FUNCTIONS:
        _tool(func)


async def index_project(project_path: str, collection: str = "", batch_size: int = 32) -> str:
    return await _indexing.index_project(project_path, collection, batch_size)


async def incremental_index_project(project_path: str, changed_files=None, batch_size: int = 32) -> str:
    return await _indexing.incremental_index_project(project_path, changed_files, batch_size)


async def search_code(query: str, collection: str = "", top_k: int = 0, rewrite_query: Optional[bool] = None) -> str:
    return await _retrieval.search_code(query, collection, top_k, rewrite_query)


async def explain_code(query: str, collection: str = "", top_k: int = 5) -> str:
    return await _retrieval.explain_code(query, collection, top_k)


async def index_agent_docs(project_path: str) -> str:
    return await _indexing.index_agent_docs(project_path)


async def search_agent_docs(query: str, collection: str = "", layer: str = None, doc_priority: str = None) -> str:
    return await _indexing.search_agent_docs(query, collection, layer, doc_priority)


async def store_memory(title: str, content: str, memory_type: str = "general", tags=None, collection: str = "", module: str = "", commit_sha: str = "", provenance: str = "", valid_days: int = None, status: str = "active") -> str:
    return await _memory.store_memory(title, content, memory_type, tags, collection, module, commit_sha, provenance, valid_days, status)


async def recall_memory(query: str, memory_type: str = None, memory_layer: str = None, collection: str = "", include_invalid: bool = False, top_k: int = 5) -> str:
    return await _memory.recall_memory(query, memory_type, memory_layer, collection, include_invalid, top_k)


async def compact_memory(collection: str, query: str = "*") -> str:
    return await _memory.compact_memory(collection, query)


async def create_agent_task(title: str, description: str, collection: str, steps=None) -> str:
    return await _execution.create_agent_task(title, description, collection, steps)


async def get_task_status(task_id: str) -> str:
    return await _execution.get_task_status(task_id)


async def approve_task_step(task_id: str, feedback: str = "approved") -> str:
    return await _execution.approve_task_step(task_id, feedback)


async def complete_task(task_id: str, note: str = "") -> str:
    return await _execution.complete_task(task_id, note)


async def resume_task(task_id: str) -> str:
    return await _execution.resume_task(task_id)


async def list_agent_tasks(collection: str = "", status: str = "") -> str:
    return await _execution.list_agent_tasks(collection, status)


async def get_project_state(collection: str) -> str:
    """PostgreSQL'den koleksiyonun tüm görev durumunu döndürür. state.md/tasks.md dosyası gerekmez."""
    return await _execution.get_project_state(collection)


async def get_active_phase(collection: str) -> str:
    """PostgreSQL'den aktif/planlanan fazı adımlarıyla döndürür."""
    return await _execution.get_active_phase(collection)


async def run_verification_plan(project_path: str, run_build: bool = True, run_tests: bool = True, run_lint: bool = False) -> str:
    return await _execution.run_verification_plan(project_path, run_build, run_tests, run_lint)


async def run_retrieval_eval(dataset_name: str, collection: str) -> str:
    return await _execution.run_retrieval_eval(dataset_name, collection)


async def get_control_plane_stats() -> str:
    return await _control.get_control_plane_stats()


async def register_project(project_path: str, collection: str = "", index_code: bool = True, index_docs: bool = True, batch_size: int = 32) -> str:
    return await _control.register_project(project_path, collection, index_code, index_docs, batch_size)


async def list_projects() -> str:
    return await _control.list_projects()


async def summarize_repository(project_path: str, collection: str = "") -> str:
    return await _control.summarize_repository(project_path, collection)


async def search_repo_architecture(query: str, collection: str = "", top_k: int = 6) -> str:
    return await _retrieval.search_repo_architecture(query, collection, top_k)


async def analyze_change_impact(project_path: str, changed_paths: list, collection: str = "") -> str:
    return await _control.analyze_change_impact(project_path, changed_paths, collection)


async def store_decision_memory(title: str, content: str, collection: str, module: str = "", commit_sha: str = "", provenance: str = "", tags=None) -> str:
    return await _memory.store_decision_memory(title, content, collection, module, commit_sha, provenance, tags)


async def search_decisions(query: str, collection: str = "", top_k: int = 5) -> str:
    return await _memory.search_decisions(query, collection, top_k)


TOOL_FUNCTIONS = [
    index_project,
    incremental_index_project,
    search_code,
    explain_code,
    index_agent_docs,
    search_agent_docs,
    store_memory,
    recall_memory,
    compact_memory,
    create_agent_task,
    get_task_status,
    approve_task_step,
    complete_task,
    resume_task,
    list_agent_tasks,
    get_project_state,
    get_active_phase,
    run_verification_plan,
    run_retrieval_eval,
    get_control_plane_stats,
    register_project,
    list_projects,
    summarize_repository,
    search_repo_architecture,
    analyze_change_impact,
    store_decision_memory,
    search_decisions,
]
