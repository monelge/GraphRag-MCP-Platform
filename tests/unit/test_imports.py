def test_core_imports() -> None:
    """Çekirdek modüllerin import edilebildiğini doğrular."""
    from src.mcp_server import app

    assert app is not None


def test_shared_imports() -> None:
    """Shared servis importlarının çalıştığını doğrular."""
    from src.shared.llm_client import LLMClient

    assert LLMClient is not None


def test_indexing_imports() -> None:
    """Indexing modül importlarının çalıştığını doğrular."""
    from src.indexing.chunkers.markdown_chunker import MarkdownChunker

    assert MarkdownChunker is not None


def test_retrieval_imports() -> None:
    """Retrieval modül importlarının çalıştığını doğrular."""
    from src.retrieval.context.context_builder import ContextBuilder

    assert ContextBuilder is not None
