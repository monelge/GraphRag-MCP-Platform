"""
CodeActRunner birim testleri.

Tüm bağımlılıklar (LLM, MCP, workspace, state machine, session, spec, context) mock'lanır.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.codeact_runner import (
    CodeActRunner,
    RunConfig,
    StepEvent,
    TDADStep,
)
from src.agent.session_context import SessionContext
from src.agent.spec_builder import TaskSpec
from src.agent.state_machine import AgentCheckpoint, CHECKPOINT_VERSION
from src.control.models.complexity_router import ModelTier, RoutingDecision
from src.control.models.escalation_manager import EscalationManager


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture
def decision():
    return RoutingDecision(
        tier=ModelTier.CHEAP,
        score=0.4,
        model="google/gemini-2.5-flash",
        base_url=None,
        token_budget=16000,
    )


@pytest.fixture
def run_config() -> RunConfig:
    return RunConfig(
        task_id="test-001",
        goal="Fix the null pointer bug",
        collection="warelogisticcbys",
        project_path="/tmp/project",
        hitl_enabled=False,  # HITL kapalı → onay beklemeden geç
    )


@pytest.fixture
def sample_spec() -> TaskSpec:
    return TaskSpec(
        task_id="test-001",
        goal="Fix the null pointer bug",
        collection="warelogisticcbys",
        project_path="/tmp/project",
        task_type="bugfix",
        affected_files=["src/foo.py"],
        affected_symbols=["my_func"],
        search_queries=["my_func bug"],
        acceptance_criteria=["tests pass"],
        test_hints=["assert result is not None"],
        language_hint="python",
    )


def _make_context_assembly():
    asm = MagicMock()
    asm.code_chunks = [{"file_path": "src/foo.py", "content": "def my_func(): pass"}]
    asm.tokens_used = 200
    asm.impact_items = []
    return asm


def _make_runner(decision, sm, sessions, spec_builder,
                 ctx_asm, escalation, llm, mcp,
                 approval_queue=None):
    return CodeActRunner(
        state_machine=sm,
        session_store=sessions,
        spec_builder=spec_builder,
        context_assembler=ctx_asm,
        escalation_manager=escalation,
        llm_client=llm,
        mcp_handler=mcp,
        approval_queue=approval_queue,
    )


# ── Ortak mock setup ──────────────────────────────────────────────────────────

@pytest.fixture
def mocks(decision, sample_spec):
    cp = AgentCheckpoint(
        task_id="test-001", goal="Fix bug", collection="c", project_path="/p"
    )
    sm = AsyncMock()
    sm.load = AsyncMock(return_value=None)
    sm.create = AsyncMock(return_value=cp)
    sm.save = AsyncMock()
    sm.create_task_record = AsyncMock()
    sm.update_task_status = AsyncMock()

    sessions = AsyncMock()
    sessions.load = AsyncMock(return_value=None)
    sessions.save = AsyncMock()
    sessions.delete = AsyncMock()

    spec_builder = MagicMock()
    spec_builder.heuristic_build = MagicMock(return_value=sample_spec)
    spec_builder.llm_build = AsyncMock(return_value=sample_spec)

    ctx_asm = AsyncMock()
    ctx_asm.assemble = AsyncMock(return_value=_make_context_assembly())

    escalation = EscalationManager()

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="def test_my_func():\n    assert my_func() is not None")

    mcp = AsyncMock()
    mcp.analyze_change_impact = AsyncMock(return_value={"impact": [], "score": 0.1})
    mcp.store_memory = AsyncMock(return_value=None)

    return {
        "cp": cp, "sm": sm, "sessions": sessions,
        "spec_builder": spec_builder, "ctx_asm": ctx_asm,
        "escalation": escalation, "llm": llm, "mcp": mcp,
        "decision": decision,
    }


# ── Helper: events topla ──────────────────────────────────────────────────────

async def collect_events(runner: CodeActRunner, config: RunConfig) -> list[StepEvent]:
    events = []
    async for event in runner.run(config):
        events.append(event)
    return events


# ── SPEC adımı testi ──────────────────────────────────────────────────────────

class TestSpecStep:
    @pytest.mark.asyncio
    async def test_spec_event_emitted(self, mocks, run_config, decision):
        with patch("src.agent.codeact_runner.get_workspace_manager") as mock_wm, \
             patch("src.agent.codeact_runner.get_complexity_router") as mock_router:

            ws_info = MagicMock()
            ws_info.path = "/tmp/ws"
            ws_info.snapshot_ref = "snap-abc"
            mock_wm.return_value.create = AsyncMock(return_value=ws_info)
            mock_wm.return_value.remove = AsyncMock()
            mock_router.return_value.route = AsyncMock(return_value=decision)

            # Patch verify to succeed
            runner = _make_runner(decision, **{k: mocks[k] for k in
                ["sm", "sessions", "spec_builder", "ctx_asm", "escalation", "llm", "mcp"]})

            with patch.object(runner, "_run_verify", new=AsyncMock(return_value=(True, "ok"))), \
                 patch.object(runner, "_commit", new=AsyncMock(return_value="abc1234")), \
                 patch.object(runner, "_reflect", new=AsyncMock(return_value="looks good")), \
                 patch.object(runner, "_analyze_impact", new=AsyncMock(return_value="low impact")):

                events = await collect_events(runner, run_config)

        steps = [e.step for e in events]
        assert "SPEC" in steps
        spec_completed = [e for e in events if e.step == "SPEC" and e.status == "completed"]
        assert spec_completed


# ── Happy-path: SPEC → COMMIT → DONE ─────────────────────────────────────────

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_loop_reaches_done(self, mocks, run_config, decision):
        with patch("src.agent.codeact_runner.get_workspace_manager") as mock_wm, \
             patch("src.agent.codeact_runner.get_complexity_router") as mock_router:

            ws_info = MagicMock()
            ws_info.path = "/tmp/ws"
            ws_info.snapshot_ref = "snap-abc"
            mock_wm.return_value.create = AsyncMock(return_value=ws_info)
            mock_wm.return_value.remove = AsyncMock()
            mock_router.return_value.route = AsyncMock(return_value=decision)

            runner = _make_runner(decision, **{k: mocks[k] for k in
                ["sm", "sessions", "spec_builder", "ctx_asm", "escalation", "llm", "mcp"]})

            with patch.object(runner, "_run_verify", new=AsyncMock(return_value=(True, "all tests pass"))), \
                 patch.object(runner, "_commit", new=AsyncMock(return_value="deadbeef")), \
                 patch.object(runner, "_reflect", new=AsyncMock(return_value="LGTM")), \
                 patch.object(runner, "_analyze_impact", new=AsyncMock(return_value="low")):

                events = await collect_events(runner, run_config)

        steps = [e.step for e in events]
        assert "DONE" in steps

        done_events = [e for e in events if e.step == "DONE"]
        assert done_events[0].status == "completed"

    @pytest.mark.asyncio
    async def test_commit_event_contains_hash(self, mocks, run_config, decision):
        with patch("src.agent.codeact_runner.get_workspace_manager") as mock_wm, \
             patch("src.agent.codeact_runner.get_complexity_router") as mock_router:

            ws_info = MagicMock()
            ws_info.path = "/tmp/ws"
            ws_info.snapshot_ref = ""
            mock_wm.return_value.create = AsyncMock(return_value=ws_info)
            mock_wm.return_value.remove = AsyncMock()
            mock_router.return_value.route = AsyncMock(return_value=decision)

            runner = _make_runner(decision, **{k: mocks[k] for k in
                ["sm", "sessions", "spec_builder", "ctx_asm", "escalation", "llm", "mcp"]})

            with patch.object(runner, "_run_verify", new=AsyncMock(return_value=(True, "ok"))), \
                 patch.object(runner, "_commit", new=AsyncMock(return_value="cafe1234")), \
                 patch.object(runner, "_reflect", new=AsyncMock(return_value="OK")), \
                 patch.object(runner, "_analyze_impact", new=AsyncMock(return_value="none")):

                events = await collect_events(runner, run_config)

        commit_events = [e for e in events if e.step == "COMMIT" and e.status == "completed"]
        assert commit_events
        assert commit_events[0].data.get("commit") == "cafe1234"


# ── VERIFY fail → escalation ──────────────────────────────────────────────────

class TestVerifyFailure:
    @pytest.mark.asyncio
    async def test_verify_fail_emits_failed_event(self, mocks, run_config, decision):
        with patch("src.agent.codeact_runner.get_workspace_manager") as mock_wm, \
             patch("src.agent.codeact_runner.get_complexity_router") as mock_router:

            ws_info = MagicMock()
            ws_info.path = "/tmp/ws"
            ws_info.snapshot_ref = ""
            mock_wm.return_value.create = AsyncMock(return_value=ws_info)
            mock_wm.return_value.remove = AsyncMock()
            mock_router.return_value.route = AsyncMock(return_value=decision)

            runner = _make_runner(decision, **{k: mocks[k] for k in
                ["sm", "sessions", "spec_builder", "ctx_asm", "escalation", "llm", "mcp"]})

            call_count = 0

            async def verify_side_effect(spec, ws):
                nonlocal call_count
                call_count += 1
                if call_count <= 6:
                    return False, "AssertionError: expected True"
                return True, "all pass"

            with patch.object(runner, "_run_verify", side_effect=verify_side_effect), \
                 patch.object(runner, "_commit", new=AsyncMock(return_value="abc")), \
                 patch.object(runner, "_reflect", new=AsyncMock(return_value="ok")), \
                 patch.object(runner, "_analyze_impact", new=AsyncMock(return_value="low")), \
                 patch.object(runner, "_wait_approval", new=AsyncMock(return_value=True)):

                events = await collect_events(runner, run_config)

        verify_failures = [e for e in events if e.step == "VERIFY" and e.status == "failed"]
        assert verify_failures, "VERIFY fail event'i yayınlanmalı"


# ── HITL timeout → SUSPENDED ──────────────────────────────────────────────────

class TestHITLTimeout:
    @pytest.mark.asyncio
    async def test_approval_rejected_leads_to_failed(self, mocks, decision):
        config = RunConfig(
            task_id="test-hitl",
            goal="Risky refactor",
            collection="c",
            project_path="/p",
            hitl_enabled=True,
        )

        with patch("src.agent.codeact_runner.get_workspace_manager") as mock_wm, \
             patch("src.agent.codeact_runner.get_complexity_router") as mock_router:

            ws_info = MagicMock()
            ws_info.path = "/tmp/ws"
            ws_info.snapshot_ref = ""
            mock_wm.return_value.create = AsyncMock(return_value=ws_info)
            mock_wm.return_value.remove = AsyncMock()
            mock_router.return_value.route = AsyncMock(return_value=decision)

            runner = _make_runner(decision, **{k: mocks[k] for k in
                ["sm", "sessions", "spec_builder", "ctx_asm", "escalation", "llm", "mcp"]})

            with patch.object(runner, "_run_verify", new=AsyncMock(return_value=(True, "ok"))), \
                 patch.object(runner, "_commit", new=AsyncMock(return_value="abc")), \
                 patch.object(runner, "_reflect", new=AsyncMock(return_value="reflection notes")), \
                 patch.object(runner, "_analyze_impact", new=AsyncMock(return_value="high")), \
                 patch.object(runner, "_wait_approval", new=AsyncMock(return_value=False)):

                events = await collect_events(runner, config)

        # Onay reddedildi → FAILED veya son adım WAITING olmalı
        statuses = [e.status for e in events]
        assert "failed" in statuses or "waiting" in statuses
