import pytest

from src.storage.neo4j_store import _validate_label, _validate_rel_type


def test_validate_label_valid() -> None:
    """Geçerli etiketlerin kabul edildiğini doğrular."""
    result = _validate_label("Module")

    assert result == "Module"


def test_validate_label_invalid() -> None:
    """Geçersiz etiketlerde hata üretildiğini doğrular."""
    with pytest.raises(ValueError):
        _validate_label("InvalidLabel")


def test_validate_rel_type_valid() -> None:
    """Geçerli ilişki tiplerinin kabul edildiğini doğrular."""
    result = _validate_rel_type("DEPENDS_ON")

    assert result == "DEPENDS_ON"


def test_validate_rel_type_invalid() -> None:
    """Geçersiz ilişki tiplerinde hata üretildiğini doğrular."""
    with pytest.raises(ValueError):
        _validate_rel_type("INVALID_REL")
