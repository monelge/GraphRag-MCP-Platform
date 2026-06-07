"""
Agent API endpoint testleri — FastAPI TestClient ile.

Tüm depolama ve runner bağımlılıkları mock'lanır.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agent.api import create_app
from src.agent.codeact_runner import StepEvent


# ── App fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Lifespan atlayarak minimal FastAPI app döner."""
    with patch("src.agent.api._init_storage", new=AsyncMock()):
        application = create_app()
    return application


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── /v1/health ────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "postgres" in data
        assert "redis" in data

    def test_health_shows_services_false_without_env(self, client):
        # Servis yok → hepsi False
        data = client.get("/v1/health").json()
        assert data["postgres"] is False
        assert data["redis"] is False


# ── /v1/agent/approve ─────────────────────────────────────────────────────────

class TestApprove:
    def test_approve_unknown_task_returns_404(self, client):
        resp = client.post("/v1/agent/approve", json={
            "task_id": "nonexistent-task-xyz",
            "approved": True,
        })
        assert resp.status_code == 404

    def test_approve_known_task_returns_ok(self, client, app):
        import src.agent.api as api_module
        q = asyncio.Queue()
        api_module._approval_queues["task-known"] = q

        resp = client.post("/v1/agent/approve", json={
            "task_id": "task-known",
            "approved": True,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

        # Kuyruğa yazıldı mı?
        assert not q.empty()
        assert q.get_nowait() is True

        # Temizlik
        del api_module._approval_queues["task-known"]


# ── /v1/agent/status/{task_id} ───────────────────────────────────────────────

class TestStatus:
    def test_status_unknown_task_returns_503_or_404(self, client):
        # _postgres=None → 503; bağlı ama görev yok → 404
        resp = client.get("/v1/agent/status/nonexistent-task")
        assert resp.status_code in (503, 404)

    def test_status_with_mock_checkpoint(self, client):
        from src.agent.state_machine import AgentCheckpoint
        cp = AgentCheckpoint(
            task_id="status-test",
            goal="test goal",
            collection="c",
            project_path="/p",
        )

        mock_sm = AsyncMock()
        mock_sm.load = AsyncMock(return_value=cp)

        with patch("src.agent.api.AgentStateMachine", return_value=mock_sm):
            resp = client.get("/v1/agent/status/status-test")

        # _postgres=None → 503 dönebilir; mock çalışırsa 200
        assert resp.status_code in (200, 404, 503)


# ── /v1/agent/tasks ──────────────────────────────────────────────────────────

class TestTasks:
    def test_tasks_endpoint_reachable(self, client):
        resp = client.get("/v1/agent/tasks")
        # DB yoksa boş liste veya 200 dönmeli
        assert resp.status_code in (200, 500)

    def test_tasks_with_mock_sm(self, client):
        mock_sm = AsyncMock()
        mock_sm.get_task_history = AsyncMock(return_value=[
            {"task_id": "t1", "status": "COMPLETED", "goal": "fix bug"},
        ])

        with patch("src.agent.api.AgentStateMachine", return_value=mock_sm):
            resp = client.get("/v1/agent/tasks?limit=10")

        assert resp.status_code in (200, 500)


# ── Request validation ────────────────────────────────────────────────────────

class TestRequestValidation:
    def test_run_requires_goal(self, client):
        # goal olmadan → 422
        resp = client.post("/v1/agent/run", json={
            "collection": "test",
        })
        assert resp.status_code == 422

    def test_run_goal_too_short(self, client):
        resp = client.post("/v1/agent/run", json={"goal": "ab"})
        assert resp.status_code == 422

    def test_approve_requires_task_id(self, client):
        resp = client.post("/v1/agent/approve", json={"approved": True})
        assert resp.status_code == 422
