"""
Sprint 2 agent birim testleri için ortak mock fixture'lar.

Tüm dış bağımlılıklar (LLM, MCP, PG, Redis, Workspace) AsyncMock ile
ikame edilir — gerçek servis gerektirmez, offline CI'da çalışır.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.state_machine import AgentCheckpoint, CHECKPOINT_VERSION
from src.control.models.complexity_router import ModelTier, RoutingDecision, TierConfig


# ── Routing & tier fixture'ları ───────────────────────────────────────────────

@pytest.fixture
def cheap_decision() -> RoutingDecision:
    return RoutingDecision(
        tier=ModelTier.CHEAP,
        score=0.5,
        model="google/gemini-2.5-flash",
        base_url=None,
        token_budget=16000,
        signals={"final_score": 0.5},
        ollama_degraded=False,
    )


@pytest.fixture
def reason_decision() -> RoutingDecision:
    return RoutingDecision(
        tier=ModelTier.REASON,
        score=0.85,
        model="anthropic/claude-sonnet-4-6",
        base_url=None,
        token_budget=32000,
        signals={"final_score": 0.85},
        ollama_degraded=False,
    )


@pytest.fixture
def local_decision() -> RoutingDecision:
    return RoutingDecision(
        tier=ModelTier.LOCAL,
        score=0.1,
        model="qwen2.5-coder:32b",
        base_url="http://localhost:11434/v1",
        token_budget=8000,
        signals={"final_score": 0.1},
        ollama_degraded=False,
    )


# ── LLMClient mock ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    """LLMClient.complete() → basit metin döner."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Mock LLM response")
    return llm


@pytest.fixture
def mock_llm_spec(mock_llm):
    """Spec adımı için JSON döndüren LLM mock'u."""
    spec_json = json.dumps({
        "task_type": "bugfix",
        "affected_files": ["src/foo.py"],
        "affected_symbols": ["my_func"],
        "search_queries": ["my_func bug"],
        "acceptance_criteria": ["test passes"],
        "test_hints": ["assert result == expected"],
        "language_hint": "python",
    })
    mock_llm.complete = AsyncMock(return_value=spec_json)
    return mock_llm


# ── MCPBridge mock ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_mcp():
    mcp = AsyncMock()
    mcp.search_code = AsyncMock(return_value=[
        {"file": "src/foo.py", "content": "def my_func(): pass", "score": 0.9}
    ])
    mcp.grep_exact_string = AsyncMock(return_value=[])
    mcp.recall_memory = AsyncMock(return_value=[])
    mcp.store_memory = AsyncMock(return_value=None)
    mcp.analyze_change_impact = AsyncMock(return_value={"impact": [], "score": 0.1})
    return mcp


# ── PostgresStore / RedisStore mock'ları ─────────────────────────────────────

@pytest.fixture
def mock_pg():
    """PostgresStore mock — asyncpg pool arayüzünü simüle eder."""
    pg = MagicMock()
    # _pool property: asyncpg pool mock
    pool = AsyncMock()
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    pool.acquire = MagicMock(return_value=conn)
    pg._pool = pool
    return pg


@pytest.fixture
def mock_redis():
    """RedisStore mock — set_raw/get_raw arayüzünü simüle eder."""
    redis = AsyncMock()
    _store: dict[str, str] = {}

    async def set_raw(key, value, ttl=None):
        _store[key] = value

    async def get_raw(key):
        return _store.get(key)

    async def delete(key):
        _store.pop(key, None)

    redis.set_raw = AsyncMock(side_effect=set_raw)
    redis.get_raw = AsyncMock(side_effect=get_raw)
    redis.delete = AsyncMock(side_effect=delete)
    redis._store = _store
    return redis


# ── WorkspaceManager mock ─────────────────────────────────────────────────────

@pytest.fixture
def mock_workspace():
    from src.agent.workspace_manager import WorkspaceInfo
    ws = AsyncMock()
    info = WorkspaceInfo(
        task_id="test-task-001",
        worktree_path="/tmp/test-workspace",
        branch_name="agent/test-task-001",
        base_commit="abc1234",
        created_at=0.0,
    )
    ws.create_workspace = AsyncMock(return_value=info)
    ws.cleanup_workspace = AsyncMock(return_value=None)
    ws.snapshot = AsyncMock(return_value="snap-abc")
    ws.restore_snapshot = AsyncMock(return_value=None)
    return ws, info


# ── AgentStateMachine mock ────────────────────────────────────────────────────

@pytest.fixture
def mock_state_machine(mock_pg, mock_redis):
    """AgentStateMachine'i mock PG+Redis ile döner."""
    from src.agent.state_machine import AgentStateMachine
    sm = AgentStateMachine(pg_store=mock_pg, redis_store=mock_redis)
    return sm


# ── Örnek checkpoint ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_checkpoint() -> AgentCheckpoint:
    return AgentCheckpoint(
        version=CHECKPOINT_VERSION,
        task_id="test-task-001",
        step="SPEC",
        current_tier="TIER_CHEAP",
        selected_model="google/gemini-2.5-flash",
        goal="Fix the bug in my_func",
        collection="warelogisticcbys",
        project_path="/tmp/project",
    )


# ── ComplexityRouter mock ─────────────────────────────────────────────────────

@pytest.fixture
def mock_router(cheap_decision):
    router = AsyncMock()
    router.route = AsyncMock(return_value=cheap_decision)
    router.route_sync = MagicMock(return_value=cheap_decision)
    router.get_config = MagicMock(return_value=TierConfig(
        model="google/gemini-2.5-flash",
        fallback="mistralai/codestral-latest",
        token_budget=16000,
    ))
    return router
