from __future__ import annotations

import pytest

from src.handlers.memory_handler import MemoryHandler
from src.memory.models.memory_models import MemoryEntry
from src.memory.stores.episodic_store import EpisodicStore


class DummyAuditLogger:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def log(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


class DummyPostgres:
    def __init__(self) -> None:
        self.log_calls: list[dict] = []

    async def log_retrieval(self, **kwargs) -> None:
        self.log_calls.append(kwargs)


class DummyCtx:
    def __init__(self) -> None:
        self.episodic = object()
        self.redis = object()
        self.audit_logger = DummyAuditLogger()
        self.postgres = DummyPostgres()


@pytest.mark.asyncio
async def test_store_memory_delegates_to_writer_and_semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = DummyCtx()
    handler = MemoryHandler(ctx)

    async def fake_write(entry, redis_store=None):
        assert entry.memory_type == "general"
        assert entry.collection == "my_collection"
        return "general-ok"

    monkeypatch.setattr(handler.memory_writer, "write", fake_write)
    result = await handler.store_memory(
        title="Test entry",
        content="This is a general memory entry.",
        memory_type="general",
        collection="my_collection",
    )

    assert result == "general-ok"
    assert ctx.audit_logger.calls, "Audit log should be called on memory write"

    async def fake_semantic(entry, redis_store=None):
        assert entry.memory_type == "semantic"
        return "semantic-ok"

    monkeypatch.setattr(handler.semantic_store, "store_semantic", fake_semantic)
    result = await handler.store_memory(
        title="Semantic entry",
        content="This is a semantic memory entry.",
        memory_type="semantic",
        collection="my_collection",
    )

    assert result == "semantic-ok"


@pytest.mark.asyncio
async def test_recall_memory_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = DummyCtx()
    handler = MemoryHandler(ctx)

    async def fake_recall(query, memory_type=None, memory_layer=None, collection=None, include_invalid=False, top_k=5):
        return [
            {
                "title": "Found memory",
                "content": "Remember this detail.",
                "memory_type": "episodic",
                "score": 0.876,
            }
        ]

    monkeypatch.setattr(handler.memory_recall, "recall", fake_recall)
    output = await handler.recall_memory("detay", top_k=1)

    assert "Found memory" in output
    assert "0.876" in output
    assert "episodic" in output


@pytest.mark.asyncio
async def test_store_decision_memory_and_search_decisions(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = DummyCtx()
    handler = MemoryHandler(ctx)

    async def fake_store_decision(title, content, collection, module="", commit_sha="", provenance="", tags=None):
        assert title == "Decision"
        assert content == "Make this decision"
        assert collection == "project_a"
        return "decision-ok"

    monkeypatch.setattr(handler.decision_store, "store_decision", fake_store_decision)
    result = await handler.store_decision_memory(
        title="Decision",
        content="Make this decision",
        collection="project_a",
    )
    assert result == "decision-ok"

    async def fake_search_decisions(query, collection, top_k):
        assert query == "decision"
        assert collection == "project_a"
        assert top_k == 2
        return [
            {"title": "Decision record", "content": "This is a decision.", "score": 0.45}
        ]

    monkeypatch.setattr(handler.decision_store, "search_decisions", fake_search_decisions)
    output = await handler.search_decisions("decision", collection="project_a", top_k=2)

    assert "Karar Hafızası" in output
    assert "Decision record" in output
    assert ctx.postgres.log_calls[0]["query_type"] == "decision_memory"


def test_memory_entry_layer_mapping() -> None:
    entry = MemoryEntry(title="X", content="Y", memory_type="architecture_decision")
    assert entry.memory_layer == "decision"

    entry = MemoryEntry(title="X", content="Y", memory_type="general")
    assert entry.memory_layer == "episodic"

    entry = MemoryEntry(title="X", content="Y", memory_type="semantic")
    assert entry.memory_layer == "semantic"


@pytest.mark.asyncio
async def test_episodic_store_search_memory_calls_hybrid_search(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict = {}

    class FakeHybridSearcher:
        def __init__(self, collection: str) -> None:
            recorded["collection"] = collection

        async def search(self, query, top_k=5, query_filter=None):
            recorded["query"] = query
            recorded["top_k"] = top_k
            recorded["query_filter"] = query_filter
            return [{"score": 0.22, "title": "hit"}]

    monkeypatch.setattr("src.retrieval.search.hybrid_search.HybridSearcher", FakeHybridSearcher)

    store = EpisodicStore()
    results = await store.search_memory(
        "bug fix",
        memory_type="known_bug",
        collection="project_a",
        top_k=2,
    )

    assert results and results[0]["title"] == "hit"
    assert recorded["collection"] == "episodic_memory"
    assert recorded["query"] == "bug fix"
    assert recorded["top_k"] == 2
    assert recorded["query_filter"] is not None
