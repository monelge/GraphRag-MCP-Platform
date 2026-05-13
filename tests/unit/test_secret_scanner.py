from src.indexing.chunkers import secret_scanner


def test_secret_scanner_redacts_medium_confidence_matches() -> None:
    """Orta güvenli eşleşmelerin redact edildiğini doğrular."""
    result = secret_scanner.scan("password=super-secret api_key=test-key")

    assert result.should_skip is False
    assert "[REDACTED:PASSWORD]" in result.redacted_text
    assert "[REDACTED:API_KEY]" in result.redacted_text


def test_secret_scanner_skips_high_confidence_matches() -> None:
    """Yüksek güvenli sırların chunk'ı skip ettiğini doğrular."""
    result = secret_scanner.scan("Authorization: Bearer very-secret-token")

    assert result.should_skip is True
    assert "[REDACTED:BEARER_TOKEN]" in result.redacted_text
