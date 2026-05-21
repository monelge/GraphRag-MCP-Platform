"""
PreLLM Context Compressor — Conservative Token Optimizasyonu.

Neden conservative?
  Yanlış silinen bir satır sessiz hallucination üretir ve debug edilmesi
  çok zordur. Token kazancı %15-30 gibi daha mütevazı ama güvenli.
"""

from __future__ import annotations

import re
import logging
from src.shared.config import config

logger = logging.getLogger(__name__)

# Lisans/copyright bloğunu tespit eden pattern (dosya başı)
_LICENSE_PATTERN = re.compile(
    r"^(#.*copyright.*\n|#.*license.*\n|/\*.*copyright[\s\S]*?\*/\n?|"
    r"<!--.*copyright[\s\S]*?-->\n?)",
    re.IGNORECASE | re.MULTILINE,
)

# Uzun docstring tespit (3 satırdan fazla üçlü tırnak bloğu)
_DOCSTRING_PATTERN = re.compile(
    r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
    re.DOTALL,
)


def compress(chunk: dict) -> dict:
    """
    Tek bir chunk'ı sıkıştırır. Orijinal chunk değiştirilmez; kopyası döner.
    """
    if not config.compressor_enabled:
        return chunk

    code_key = "code" if "code" in chunk else "content"
    original_text = chunk.get(code_key) or ""

    if not original_text or len(original_text) < 200:
        # Zaten kısa — sıkıştırmaya değmez
        return chunk

    try:
        compressed = _compress_text(original_text, chunk.get("language", ""))
    except Exception as exc:
        logger.warning("Compressor hata (%s): %s", chunk.get("name", "?"), exc)
        return chunk

    original_len = len(original_text)
    compressed_len = len(compressed)
    ratio = compressed_len / max(original_len, 1)

    # Güvenlik tabanı: orijinalin %60'ından aşağı inme
    if ratio < config.compressor_max_ratio:
        logger.debug(
            "Compressor sıkıştırmayı geri aldı: %s (ratio %.2f < %.2f)",
            chunk.get("name", "?"), ratio, config.compressor_max_ratio,
        )
        compressed = original_text
        ratio = 1.0

    result = dict(chunk)
    result[code_key] = compressed
    result["_original_chars"] = original_len
    result["_compressed_chars"] = len(compressed)
    result["_compression_ratio"] = round(ratio, 3)
    return result


def compress_all(chunks: list[dict]) -> list[dict]:
    """
    Chunk listesini sıkıştırır. Her chunk bağımsız; hata birini bozmaz.
    """
    return [compress(c) for c in chunks]


# ── Dahili Yardımcı Fonksiyonlar ─────────────────────────────────────────────

def _compress_text(text: str, language: str) -> str:
    """
    Metin üzerinde tüm conservative adımları sırayla uygular.
    """
    # 1. Lisans/copyright başlıklarını kaldır
    text = _remove_license_header(text)

    # 2. Docstring'leri kısalt (ilk 3 satır + "...")
    text = _truncate_docstrings(text)

    # 3. Ardışık boş satırları sıkıştır (3+ → 1)
    text = _collapse_blank_lines(text)

    # 4. Satır sonu beyaz boşluk temizle
    text = "\n".join(line.rstrip() for line in text.splitlines())

    return text.strip()


def _remove_license_header(text: str) -> str:
    """
    Dosya başındaki lisans/copyright bloğunu kaldırır.
    Yalnızca ilk 20 satırda arar — kod içinde rastgele silmemek için.
    """
    lines = text.splitlines(keepends=True)
    head = "".join(lines[:20])
    m = _LICENSE_PATTERN.search(head)
    if m and m.start() < 5:  # Gerçekten başta ise
        return text[m.end():]
    return text


def _truncate_docstrings(text: str) -> str:
    """
    3 satırdan uzun docstring'leri ilk 3 satır + "..." olarak kısaltır.
    Tek satırlık docstring'lere dokunulmaz.
    """
    def _shorten(match: re.Match) -> str:
        block = match.group(0)
        inner_lines = block.splitlines()
        if len(inner_lines) <= 4:
            return block
        quote = '"""' if '"""' in block else "'''"
        short_lines = inner_lines[:4]
        return "\n".join(short_lines) + f'\n    {quote}  # ... (kısaltıldı)\n'

    return _DOCSTRING_PATTERN.sub(_shorten, text)


def _collapse_blank_lines(text: str) -> str:
    """
    3 veya daha fazla ardışık boş satırı tek boş satıra indirir.
    """
    return re.sub(r"\n{3,}", "\n\n", text)
