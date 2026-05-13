from src.indexing.chunkers.markdown_chunker import MarkdownChunker


def test_chunker_basic() -> None:
    """Başlık hiyerarşisinin chunk metadata'sına taşındığını doğrular."""
    chunker = MarkdownChunker()
    test_md = """# Main Title
Some content here.

## Sub Title
More content."""

    chunks = chunker._chunk_text(test_md, "test.md", "test", "normal", False)

    assert chunks
    assert chunks[0].h1 == "Main Title"


def test_chunker_code_block_preserved() -> None:
    """Kod bloklarının içerikte korunarak taşındığını doğrular."""
    chunker = MarkdownChunker()
    test_md = """# Title
```python
def foo():
    pass
```
"""

    chunks = chunker._chunk_text(test_md, "test.md", "test", "normal", False)

    assert any("```python" in chunk.content for chunk in chunks)
