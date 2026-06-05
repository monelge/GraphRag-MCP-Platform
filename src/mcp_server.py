"""Entry-point facade — Docker CMD ve MCP client config bu dosyayı kullanır."""

import os
import sys

# ONNX Runtime ve diğer kütüphanelerin stdout'a gürültü basmasını engelle
os.environ["ORT_LOGGING_LEVEL"] = "3"  # ERROR level
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Real stdout'u MCP transportu için sakla
# Bazı kütüphaneler (onnxruntime, tree-sitter vb.) C-level stdout (FD 1) kullanabilir.
# Python sys.stdout'u erkenden stderr'e yönlendirerek MCP protokolünü koruyoruz.
_original_stdout = sys.stdout
sys.stdout = sys.stderr

from src.mcp.server import (
    _app_ctx,
    _control,
    _execution,
    _indexing,
    _memory,
    _retrieval,
    app,
)
from src.mcp.tool_registry import (
    analyze_change_impact,
    approve_task_step,
    complete_task,
    compact_memory,
    create_agent_task,
    execute_agent_task,
    explain_code,
    get_control_plane_stats,
    get_task_status,
    index_agent_docs,
    index_project,
    incremental_index_project,
    list_agent_tasks,
    list_projects,
    recall_memory,
    register_project,
    resume_task,
    run_retrieval_eval,
    run_verification_plan,
    search_agent_docs,
    search_code,
    search_decisions,
    search_repo_architecture,
    store_decision_memory,
    store_memory,
    summarize_repository,
    grep_exact_string,
)

__all__ = [
    "app",
    "_app_ctx",
    "_indexing",
    "_retrieval",
    "_memory",
    "_execution",
    "_control",
    "index_project",
    "incremental_index_project",
    "search_code",
    "explain_code",
    "index_agent_docs",
    "search_agent_docs",
    "execute_agent_task",
    "store_memory",
    "recall_memory",
    "compact_memory",
    "create_agent_task",
    "get_task_status",
    "approve_task_step",
    "complete_task",
    "resume_task",
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
    "grep_exact_string",
]

if __name__ == "__main__":
    sys.stdout = _original_stdout
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if transport == "sse":
        import uvicorn
        host = os.environ.get("UVICORN_HOST", "0.0.0.0")
        port = int(os.environ.get("UVICORN_PORT", "8000"))
        # FastMCP 1.6.x — sse_app() ASGI uygulamasini dondurur
        sse_app = app.sse_app()
        uvicorn.run(sse_app, host=host, port=port, log_level="info")
    else:
        app.run(transport="stdio")
