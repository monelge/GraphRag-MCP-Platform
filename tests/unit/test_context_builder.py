from src.retrieval.context.context_builder import ContextBuilder, compute_final_score


def test_compute_final_score_prefers_function_chunks() -> None:
    """Fonksiyon chunk'larının tip bonusu aldığını doğrular."""
    function_score = compute_final_score({"type": "function", "score": 0.7, "rerank_score": 0.7})
    module_score = compute_final_score({"type": "module", "score": 0.7, "rerank_score": 0.7})

    assert function_score > module_score


def test_context_builder_filters_full_file_chunks_for_factual_queries() -> None:
    """Factual sorgularda file chunk'larının filtrelendiğini doğrular."""
    builder = ContextBuilder(token_budget=20, query_type="factual_doc")
    chunks = [
        {"chunk_id": "file-1", "type": "file", "content": "x" * 20, "score": 0.9},
        {"chunk_id": "fn-1", "type": "function", "content": "y" * 20, "score": 0.8},
    ]

    selected = builder.build(chunks)

    assert [chunk["chunk_id"] for chunk in selected] == ["fn-1"]


def test_context_builder_returns_top_chunk_when_budget_is_tight() -> None:
    """Bütçe dar olduğunda en yüksek skorlu chunk'ın korunduğunu doğrular."""
    builder = ContextBuilder(token_budget=1, query_type="architecture_analysis")
    chunks = [
        {"chunk_id": "top", "type": "function", "content": "a" * 120, "score": 0.9},
        {"chunk_id": "low", "type": "function", "content": "b" * 120, "score": 0.4},
    ]

    selected = builder.build(chunks)

    assert len(selected) == 1
    assert selected[0]["chunk_id"] == "top"
