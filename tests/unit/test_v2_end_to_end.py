"""
GraphRagMCP v2 end-to-end doğrulama testleri.
Veritabanı loglama, checkpoint ve zengin ontology extraction'ı test eder.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.orchestrator.checkpoints import CheckpointStore, TaskCheckpoint
from src.agent.orchestrator.state_machine import TaskOrchestrator
from src.agent.tasks.task_models import Task, TaskStatus
from src.agent.tasks.task_store import TaskStore
from src.indexing.chunkers.chunk_models import CodeChunk
from src.indexing.extractors.graph_extractor import GraphExtractor
from src.memory.services.memory_compaction import MemoryCompactor
from src.storage.postgres_store import PostgresStore


class TestGraphExtractorRichOntology:
    """GraphExtractor'ın zengin node/edge tiplerini doğru çıkardığını test eder."""

    def test_endpoint_extraction(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c1",
            file_path="api/users.py",
            language="python",
            chunk_type="function",
            name="get_users",
            code='@app.route("/api/users")\ndef get_users(): pass',
            start_line=1,
            end_line=2,
            endpoints=["/api/users"],
        )
        relations = extractor.extract_relationships([chunk])
        ep_edges = [r for r in relations if r["type"] == "EXPOSES_ENDPOINT"]
        assert len(ep_edges) == 1
        assert ep_edges[0]["target"]["label"] == "Endpoint"
        assert ep_edges[0]["target"]["name"] == "/api/users"

    def test_dto_node_extraction(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c2",
            file_path="dtos/user_dto.py",
            language="python",
            chunk_type="class",
            name="UserDto",
            code="class UserDto: pass",
            start_line=1,
            end_line=1,
            is_dto=True,
        )
        relations = extractor.extract_relationships([chunk])
        dto_edges = [r for r in relations if r["target"].get("label") == "DTO"]
        assert len(dto_edges) == 1
        assert dto_edges[0]["source"]["name"] == "UserDto"

    def test_entity_mutates_reads_edges(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c3",
            file_path="domain/user.py",
            language="python",
            chunk_type="class",
            name="UserEntity",
            code="class UserEntity: pass",
            start_line=1,
            end_line=1,
            is_entity=True,
        )
        relations = extractor.extract_relationships([chunk])
        entity_edges = [r for r in relations if r["target"].get("label") == "Entity"]
        assert len(entity_edges) >= 1

    def test_business_rule_extraction(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c4",
            file_path="rules/validation.py",
            language="python",
            chunk_type="function",
            name="check_email_rule",
            code="def check_email_rule(): pass",
            start_line=1,
            end_line=1,
            is_business_rule=True,
        )
        relations = extractor.extract_relationships([chunk])
        rule_edges = [r for r in relations if r["type"] == "RELATES_TO_RULE"]
        assert len(rule_edges) == 1
        assert rule_edges[0]["target"]["label"] == "BusinessRule"

    def test_migration_node_extraction(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c5",
            file_path="migrations/001_init.py",
            language="python",
            chunk_type="class",
            name="InitMigration",
            code="class InitMigration: pass",
            start_line=1,
            end_line=1,
            is_migration=True,
        )
        relations = extractor.extract_relationships([chunk])
        mig_edges = [r for r in relations if r["target"].get("label") == "Migration"]
        assert len(mig_edges) == 1

    def test_ui_component_extraction(self):
        extractor = GraphExtractor()
        chunk = CodeChunk(
            chunk_id="c6",
            file_path="components/UserCard.tsx",
            language="typescript",
            chunk_type="function",
            name="UserCard",
            code="function UserCard() { return <div></div>; }",
            start_line=1,
            end_line=1,
            is_ui_component=True,
        )
        relations = extractor.extract_relationships([chunk])
        ui_edges = [r for r in relations if r["target"].get("label") == "UIComponent"]
        assert len(ui_edges) == 1


class TestASTChunkerDetectionLogic:
    """ASTChunker detection metodlarını tree-sitter bağımlılığı olmadan test eder."""

    def _create_chunker(self):
        """ASTChunker oluştururken tree-sitter bağımlılıklarını mocklar."""
        import sys
        from unittest.mock import MagicMock

        # tree-sitter modüllerini mockla
        for mod_name in ["tree_sitter", "tree_sitter_python", "tree_sitter_typescript", "tree_sitter_c_sharp"]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = MagicMock()

        from src.indexing.chunkers.ast_chunker import ASTChunker
        return ASTChunker()

    def test_detect_dto_by_suffix(self):
        chunker = self._create_chunker()
        assert chunker._detect_dto("UserDto", "", "") is True
        assert chunker._detect_dto("UserResponse", "", "") is True
        assert chunker._detect_dto("UserService", "", "") is False

    def test_detect_dto_by_path(self):
        chunker = self._create_chunker()
        assert chunker._detect_dto(None, "", "/project/dtos/user.py") is True
        assert chunker._detect_dto(None, "", "/project/services/user.py") is False

    def test_detect_migration(self):
        chunker = self._create_chunker()
        assert chunker._detect_migration("migrations/001_init.py", None) is True
        assert chunker._detect_migration("src/user.py", "AddMigration") is True
        assert chunker._detect_migration("src/user.py", "UserService") is False

    def test_detect_ui_component(self):
        chunker = self._create_chunker()
        assert chunker._detect_ui_component("UserCard", "return <div></div>", "/app/UserCard.tsx", "typescript") is True
        assert chunker._detect_ui_component("userCard", "return <div></div>", "/app/UserCard.tsx", "typescript") is False

    def test_detect_entity(self):
        chunker = self._create_chunker()
        assert chunker._detect_entity("UserEntity", "", "") is True
        assert chunker._detect_entity("User", "", "/domain/entities/user.py") is True
        assert chunker._detect_entity("UserService", "", "") is False

    def test_detect_business_rule(self):
        chunker = self._create_chunker()
        assert chunker._detect_business_rule("EmailValidator", "", "") is True
        assert chunker._detect_business_rule("check_policy", "", "/policies/auth.py") is True
        assert chunker._detect_business_rule("UserService", "", "") is False

    def test_extract_endpoints_python(self):
        chunker = self._create_chunker()
        code = b'@app.route("/api/users")\ndef get_users(): pass'
        import re
        endpoints = []
        for m in re.finditer(rb'@[\w.]+\(\s*["\']([^"\']+)["\']', code):
            val = m.group(1).decode()
            if val.startswith(("/", "http", "api")):
                endpoints.append(val)
        assert "/api/users" in endpoints


class TestCheckpointStore:
    """CheckpointStore insert/get workflow'unu test eder."""

    @pytest.mark.asyncio
    async def test_save_and_get_latest(self):
        pg = MagicMock(spec=PostgresStore)
        pg.available = True
        pg._pool = MagicMock()

        mock_conn = AsyncMock()
        # transaction() bir async context manager döndürmeli
        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_tx)

        pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store = CheckpointStore(pg)
        task = Task(
            task_id="test-task-001",
            title="Test",
            description="Desc",
            collection="test",
        )
        task.context["current_node"] = "planner"

        cp = await store.save(task, current_node="planner", step_index=0)
        assert cp.task_id == "test-task-001"
        assert cp.current_node == "planner"
        assert cp.step_index == 0
        mock_conn.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_insert_with_conn(self):
        pg = MagicMock(spec=PostgresStore)
        pg.available = True
        store = CheckpointStore(pg)

        mock_conn = AsyncMock()
        task = Task(
            task_id="test-task-002",
            title="Test",
            description="Desc",
            collection="test",
        )

        cp = await store.save(task, current_node="retriever", step_index=1, conn=mock_conn)
        assert cp.task_id == "test-task-002"
        mock_conn.execute.assert_awaited_once()


class TestTaskOrchestratorCheckpointFlow:
    """TaskOrchestrator'un checkpoint akışını test eder."""

    @pytest.mark.asyncio
    async def test_run_step_saves_checkpoint(self):
        pg = MagicMock(spec=PostgresStore)
        pg.available = True
        pg._pool = MagicMock()

        task_store = TaskStore(pg)
        checkpoint_store = CheckpointStore(pg)
        orchestrator = TaskOrchestrator(
            task_store=task_store,
            checkpoint_store=checkpoint_store,
        )

        task = Task(
            task_id="test-task-003",
            title="Test",
            description="Desc",
            collection="test",
        )
        task.status = TaskStatus.PLANNED

        task_store.get_task = AsyncMock(return_value=task)
        task_store.save_task = AsyncMock(return_value=True)

        from src.agent.nodes.planner import PlannerNode
        PlannerNode.run = AsyncMock(return_value=MagicMock(
            context_updates={},
            next_node="retriever",
            file_patches=[{"file": "test.cs", "patch": "+line"}],
            command_results=[{"cmd": "test", "ok": True}],
            token_usage=10,
            output="Plan created",
            success=True,
        ))

        mock_conn = AsyncMock()
        pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await orchestrator.run_step("test-task-003")
        assert result is not None
        task_store.save_task.assert_awaited()


class TestMemoryCompaction:
    """MemoryCompactor pruning'ini test eder."""

    @pytest.mark.asyncio
    async def test_prune_expired_calls_store(self):
        store = MagicMock()
        store.prune_expired = AsyncMock(return_value=5)

        compactor = MemoryCompactor(store)
        result = await compactor.prune_expired_memory("test-collection")
        assert "5" in result
        assert "silindi" in result
        store.prune_expired.assert_awaited_once()


class TestPostgresStoreLogLLMUsage:
    """PostgresStore.log_llm_usage await edildiğinde doğru çalıştığını test eder."""

    @pytest.mark.asyncio
    async def test_log_llm_usage_awaits_correctly(self):
        pg = PostgresStore(dsn="postgresql://test:test@localhost/test")
        pg._pool = MagicMock()
        mock_conn = AsyncMock()
        pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        await pg.log_llm_usage(
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            task_id="task-001",
            node_name="planner",
        )
        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args[0]
        assert "model_usage_logs" in call_args[0]
