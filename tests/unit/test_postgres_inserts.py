"""
retrieval_logs ve audit_events INSERT regression testleri.

Neden bu testler?
1. retrieval_handler.py'de logger tanımsız olduğunda NameError fırlatıp
   log_retrieval çağrısının hiç yapılmaması sorununu kapsar.
2. AuditLogger._pg'nin None kalması durumunda audit_events'in sessizce
   atlanması sorununu kapsar.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. retrieval_handler logger regression ────────────────────────────────────

def test_retrieval_handler_has_logger() -> None:
    """retrieval_handler modülünün logger nesnesi tanımlı olmalı."""
    import logging

    from src.handlers import retrieval_handler

    # logger değişkeni modül içinde mevcut olmalı
    assert hasattr(retrieval_handler, "logger"), "retrieval_handler.logger tanımlı değil"
    assert isinstance(retrieval_handler.logger, logging.Logger)


@pytest.mark.asyncio
async def test_log_retrieval_called_after_successful_search() -> None:
    """
    Başarılı bir search_code çağrısı sonunda postgres.log_retrieval'ın
    await edildiğini doğrular.
    NameError (logger tanımsız) bu çağrıyı engelliyordu.
    """
    from src.control.observability.tracer import PipelineTracer
    from src.handlers.retrieval_handler import RetrievalHandler
    from src.retrieval.ranking.answerability import Confidence

    # AppContext mock
    ctx = MagicMock()
    ctx.redis.get_retrieval = AsyncMock(return_value=None)
    ctx.redis.find_similar_cached_query = AsyncMock(return_value=None)
    ctx.redis.set_query_embedding = AsyncMock()
    ctx.redis.set_retrieval = AsyncMock()
    ctx.postgres.log_retrieval = AsyncMock()
    ctx.postgres._pool = MagicMock()  # pool dolu gibi göster
    ctx.audit_logger = None
    ctx.metrics = None
    ctx.neo4j = MagicMock()
    ctx.tracer = PipelineTracer

    fake_chunk = {
        "name": "foo",
        "type": "function",
        "file": "foo.py",
        "lines": "1-10",
        "language": "python",
        "code": "def foo(): pass",
        "score": 0.9,
    }

    mock_assessment = MagicMock()
    mock_assessment.confidence = Confidence.ANSWERABLE
    mock_assessment.top1_score = 0.9
    mock_assessment.is_failure = False
    mock_assessment.reason = ""

    with (
        patch("src.handlers.retrieval_handler.DenseEmbedder") as MockEmb,
        patch("src.handlers.retrieval_handler.HybridSearcher") as MockHS,
        patch("src.handlers.retrieval_handler.LocalSearcher") as MockLS,
        patch("src.handlers.retrieval_handler.GraphExpander") as MockGE,
        patch("src.handlers.retrieval_handler.assess_answerability", return_value=mock_assessment),
        patch("src.handlers.retrieval_handler.compress_chunks", side_effect=lambda x: x),
        patch("src.handlers.retrieval_handler.get_budget_chars", return_value=4000),
        patch("src.handlers.retrieval_handler.fail_fast_token"),
        patch("src.handlers.retrieval_handler.classify_query", return_value="factual_doc"),
        patch("src.handlers.retrieval_handler.should_rewrite", return_value=False),
        patch("src.handlers.retrieval_handler.ContextBuilder") as MockCB,
        patch("src.handlers.retrieval_handler.get_model", return_value="gpt-4o-mini"),
    ):
        emb_instance = MockEmb.return_value
        emb_instance.embed_batch = AsyncMock(return_value=[[0.1] * 8])

        # factual_doc → LocalSearcher kullanır
        ls_instance = MockLS.return_value
        ls_instance.search = AsyncMock(return_value=[fake_chunk])

        hs_instance = MockHS.return_value
        hs_instance.search = AsyncMock(return_value=[fake_chunk])

        ge_instance = MockGE.return_value
        ge_instance.augment_candidates = AsyncMock(return_value=[fake_chunk])
        ge_instance.expand = AsyncMock(return_value=[])
        ge_instance.get_centrality = AsyncMock(return_value={})

        ctx.reranker.rerank = MagicMock(return_value=[fake_chunk])
        ctx.deduplicator.deduplicate = MagicMock(return_value=[fake_chunk])

        cb_instance = MockCB.return_value
        cb_instance.build = MagicMock(return_value=[fake_chunk])

        handler = RetrievalHandler(ctx)
        result = await handler.search_code("test query", collection="testcol")

    # log_retrieval çağrıldı mı?
    ctx.postgres.log_retrieval.assert_awaited_once()
    call_kwargs = ctx.postgres.log_retrieval.call_args.kwargs
    assert call_kwargs["collection"] == "testcol"
    assert call_kwargs["cache_hit"] is False


# ── 2. AuditLogger._pg module-level set regression ───────────────────────────

def test_audit_logger_pg_set_at_module_level() -> None:
    """
    server.py modülü yüklendiğinde _audit._pg None olmamalı.
    set_postgres artık lifespan değil module seviyesinde çağrılır.
    """
    from src.mcp.server import _audit, _postgres

    assert _audit._pg is _postgres, (
        "_audit._pg None; set_postgres lifespan dışında çağrılmıyor olabilir"
    )


@pytest.mark.asyncio
async def test_audit_logger_log_calls_pg_when_pool_set() -> None:
    """
    AuditLogger.log(), _pg.log_audit_event'i await etmeli.
    _pg None ise erken dönmeli (sessiz); _pg set ise INSERT yapmalı.
    """
    from src.control.observability.audit import AuditLogger
    from src.storage.postgres_store import PostgresStore

    pg_mock = MagicMock(spec=PostgresStore)
    pg_mock.log_audit_event = AsyncMock()

    audit = AuditLogger(pg=pg_mock)
    await audit.log(
        event_type="retrieval_request",
        collection="col",
        summary="test",
    )

    pg_mock.log_audit_event.assert_awaited_once()
    call_kwargs = pg_mock.log_audit_event.call_args.kwargs
    assert call_kwargs["event_type"] == "retrieval_request"
    assert call_kwargs["collection"] == "col"


@pytest.mark.asyncio
async def test_audit_logger_log_silent_when_pg_none() -> None:
    """_pg None olduğunda log() exception fırlatmadan erken dönmeli."""
    from src.control.observability.audit import AuditLogger

    audit = AuditLogger()  # _pg = None
    # Exception fırlatmamalı
    await audit.log(event_type="test_event")


# ── 3. PostgresStore.log_retrieval & log_audit_event pool guard ───────────────

@pytest.mark.asyncio
async def test_log_retrieval_silent_when_pool_none() -> None:
    """_pool None iken log_retrieval exception fırlatmadan dönmeli."""
    from src.storage.postgres_store import PostgresStore

    store = PostgresStore(dsn="postgresql://fake/fake")
    # connect() çağrılmadı → _pool None
    await store.log_retrieval(collection="col", redacted_query="q")


@pytest.mark.asyncio
async def test_get_retrieval_stats_silent_when_pool_none() -> None:
    """_pool None iken get_retrieval_stats boş liste döndürmeli."""
    from src.storage.postgres_store import PostgresStore

    store = PostgresStore(dsn="postgresql://fake/fake")
    result = await store.get_retrieval_stats(days=7)
    assert result == []


@pytest.mark.asyncio
async def test_get_audit_stats_silent_when_pool_none() -> None:
    """_pool None iken get_audit_stats boş dict döndürmeli."""
    from src.storage.postgres_store import PostgresStore

    store = PostgresStore(dsn="postgresql://fake/fake")
    result = await store.get_audit_stats(days=7)
    assert result == {"summary": [], "recent": []}


@pytest.mark.asyncio
async def test_get_control_plane_stats_includes_retrieval_and_audit() -> None:
    """get_control_plane_stats çıktısında retrieval ve audit bölümleri bulunmalı."""
    from src.handlers.control_handler import ControlHandler

    ctx = MagicMock()
    ctx.model_gateway.get_stats.return_value = {
        "total_calls": 5,
        "total_tokens": 1000,
        "total_latency_ms": 3000.0,
        "per_model_stats": {},
    }
    ctx.postgres.get_llm_usage_stats = AsyncMock(return_value=[])
    ctx.postgres.get_retrieval_stats = AsyncMock(return_value=[
        {
            "collection": "testcol",
            "query_type": "factual_doc",
            "calls": 10,
            "cache_hits": 2,
            "answerability_fails": 1,
            "avg_latency_ms": 120,
            "avg_hit_count": 4.5,
            "avg_top1_score": 0.82,
        }
    ])
    ctx.postgres.get_audit_stats = AsyncMock(return_value={
        "summary": [{"event_type": "retrieval_request", "count": 8, "last_seen": "2026-05-14"}],
        "recent": [],
    })

    handler = ControlHandler(ctx, indexing=MagicMock())
    result = await handler.get_control_plane_stats()

    assert "Retrieval" in result
    assert "testcol" in result
    assert "Audit" in result
    assert "retrieval_request" in result
