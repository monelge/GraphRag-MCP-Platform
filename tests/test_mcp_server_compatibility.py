import inspect

import pytest

from src import mcp_server
from src.handlers import AppContext, ExecutionHandler, IndexingHandler, RetrievalHandler


EXPECTED_TOOLS = {
    "index_project",
    "incremental_index_project",
    "search_code",
    "explain_code",
    "index_agent_docs",
    "search_agent_docs",
    "store_memory",
    "recall_memory",
    "compact_memory",
    "create_agent_task",
    "get_task_status",
    "approve_task_step",
    "list_agent_tasks",
    "run_verification_plan",
    "run_retrieval_eval",
    "get_control_plane_stats",
    "register_project",
    "list_projects",
    "summarize_repository",
    "search_repo_architecture",
    "analyze_change_impact",
    "store_decision_memory",
    "search_decisions",
}


def _tool_names(app) -> set[str]:
    manager = getattr(app, "_tool_manager", None)
    if manager is not None:
        tools = getattr(manager, "_tools", None)
        if isinstance(tools, dict):
            return {getattr(tool, "name", name) for name, tool in tools.items()}

    tools = getattr(app, "tools", None)
    if isinstance(tools, dict):
        return {getattr(tool, "name", name) for name, tool in tools.items()}

    raise AssertionError("FastMCP tool registry yapısı okunamadı")


def test_app_tools_registered() -> None:
    """Facade wrapper'ların FastMCP üzerinde kayıtlı olduğunu doğrular."""
    tool_names = _tool_names(mcp_server.app)
    assert EXPECTED_TOOLS.issubset(tool_names)


def test_di_singletons_initialized() -> None:
    """mcp_server içindeki handler ve context örnekleri doğru türde olmalı."""
    assert isinstance(mcp_server._app_ctx, AppContext)
    assert isinstance(mcp_server._indexing, IndexingHandler)
    assert isinstance(mcp_server._retrieval, RetrievalHandler)
    assert isinstance(mcp_server._execution, ExecutionHandler)
    assert mcp_server._indexing.ctx is mcp_server._app_ctx
    assert mcp_server._execution.retrieval is mcp_server._retrieval


def test_wrapper_signatures_preserved() -> None:
    """Kritik wrapper signature'larının geriye dönük uyumunu doğrular."""
    index_sig = inspect.signature(mcp_server.index_project)
    assert list(index_sig.parameters) == ["project_path", "collection", "batch_size"]
    assert index_sig.parameters["collection"].default == ""
    assert index_sig.parameters["batch_size"].default == 32

    search_sig = inspect.signature(mcp_server.search_code)
    assert list(search_sig.parameters) == ["query", "collection", "top_k", "rewrite_query"]
    assert search_sig.parameters["top_k"].default == 0
    assert search_sig.parameters["rewrite_query"].default is None


@pytest.mark.asyncio
async def test_wrapper_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper'ların ilgili handler method'larına delegasyon yaptığını doğrular."""
    calls: list[tuple] = []

    async def fake_index(project_path: str, collection: str = "", batch_size: int = 32) -> str:
        calls.append((project_path, collection, batch_size))
        return "ok"

    monkeypatch.setattr(mcp_server._indexing, "index_project", fake_index)
    result = await mcp_server.index_project("/repo", "demo", 7)

    assert result == "ok"
    assert calls == [("/repo", "demo", 7)]
