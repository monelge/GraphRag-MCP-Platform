from __future__ import annotations

"""Dosya uzantısından dil tespiti yapan hafif yardımcı."""

from pathlib import Path


class LanguageDetector:
    """İndeksleme öncesi desteklenen dili uzantıdan türetir."""

    _MAPPING = {
        ".py": "python",
        ".cs": "csharp",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".dart": "dart",
        ".go": "go",
        ".java": "java",
        ".md": "markdown",
    }

    def detect(self, file_path: str) -> str:
        """Uzantıya göre dil adını döndürür."""
        return self._MAPPING.get(Path(file_path).suffix.lower(), "unknown")

    def is_supported(self, file_path: str) -> bool:
        """Dosyanın desteklenen bir dil uzantısına sahip olup olmadığını döndürür."""
        return self.detect(file_path) != "unknown"


_DEFAULT_DETECTOR = LanguageDetector()


def detect(file_path: str) -> str:
    """Geriye dönük uyumluluk için modül seviyesinde dil tespiti yapar."""
    return _DEFAULT_DETECTOR.detect(file_path)


def is_supported(file_path: str) -> bool:
    """Geriye dönük uyumluluk için modül seviyesinde destek kontrolü yapar."""
    return _DEFAULT_DETECTOR.is_supported(file_path)
