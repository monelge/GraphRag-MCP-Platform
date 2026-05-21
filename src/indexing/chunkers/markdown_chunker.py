"""
MarkdownChunker — Faz 1 Header-Aware Markdown Bölücü

Neden header-aware?
  backend.md, frontend.md gibi rehber dosyalar H1/H2/H3 başlıkları ile
  bölümlere ayrılmıştır. Başlık hiyerarşisini koruyarak bölme yapılmazsa
  LLM "ADIM 3 — Klasör yapısı" bölümünü bulmak için tüm dosyayı okumak zorunda kalır.

Temel kurallar:
  1. Kod bloğu bütünlüğü: ``` fence içindeki içerik asla iki chunk'a bölünmez
  2. Tablo bütünlüğü: | satırları tek chunk; >800 token → satır grupları + başlık tekrarı
  3. Chunk boyutu: 300–800 token (~1200–3200 karakter; 1 token ≈ 4 karakter)
  4. SecretScanner: risk > 0.8 → chunk atlanır
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.shared.config import config
from .chunk_models import AgentDocChunk
from . import secret_scanner

# Dosya adından layer ve doc_priority belirleme tablosu.
_FILE_LAYER_MAP: dict[str, str] = {
    "security.md": "security",
    "rules.md": "rules",
    "backend.md": "backend",
    "frontend.md": "frontend",
    "entity-template.md": "entity",
    "init.md": "init",
    "state.md": "state",
    "tasks.md": "state",
    "context.md": "state",
    "ai-rules.md": "rules",
    "pr-checklist.md": "rules",
    "multi-dbcontext.md": "backend",
}

_FILE_PRIORITY_MAP: dict[str, str] = {
    "security.md": "critical",
    "rules.md": "critical",
    "backend.md": "high",
    "frontend.md": "high",
    "entity-template.md": "high",
    "init.md": "high",
    "state.md": "normal",
    "tasks.md": "normal",
    "context.md": "normal",
}

# session_start'ta zorunlu okunan dosyalar
_REQUIRED_ON_START: set[str] = {
    "state.md", "context.md", "tasks.md", "rules.md", "security.md"
}

# SecretScanner'ı bypass eden dosya pattern'leri (genellikle documentation)
_WHITELIST_SKIP_SCANNING: set[str] = {
    "security.md",
    "rules.md",
    "backend.md",
    "frontend.md",
    "backend-architecture.md",
    "mobile-plan.md",
    "mobile-state.md",
    "mobile-tasks.md",
    "state.md",
    "tasks.md",
}


@dataclass
class _Section:
    """
    Markdown parse aşamasındaki ara temsil.
    Her Section bir H1/H2/H3 başlık bloğudur; henüz chunk'lara bölünmemiştir.
    """
    h1: str = ""
    h2: str = ""
    h3: str = ""
    lines: list[str] = field(default_factory=list)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_id(relative_path: str, h1: str, h2: str, h3: str,
               section_idx: int, chunk_idx: int) -> str:
    """Konum tabanlı stabil kimlik."""
    key = f"{relative_path}|{h1}|{h2}|{h3}|{section_idx}|{chunk_idx}"
    return _sha256(key)


class MarkdownChunker:

    def chunk_file(self, file_path: str, relative_path: Optional[str] = None) -> list[AgentDocChunk]:
        """Dosyayı okur ve chunk listesi döndürür."""
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        rel = relative_path or str(path)
        filename = path.name.lower()

        layer = _FILE_LAYER_MAP.get(filename, "")
        doc_priority = _FILE_PRIORITY_MAP.get(filename, "normal")
        required = filename in _REQUIRED_ON_START
        
        # Bypass yalnızca geliştirme/test senaryolarında explicit olarak açılabilir.
        skip_scanning = (
            config.allow_secret_bypass
            and config.environment != "production"
            and filename in _WHITELIST_SKIP_SCANNING
        )

        return self._chunk_text(content, rel, layer, doc_priority, required, skip_scanning)

    # ------------------------------------------------------------------
    # İç metodlar
    # ------------------------------------------------------------------

    def _chunk_text(
        self,
        content: str,
        relative_path: str,
        layer: str,
        doc_priority: str,
        required_on_session_start: bool,
        skip_scanning: bool = False,
    ) -> list[AgentDocChunk]:
        sections = self._parse_sections(content)
        result: list[AgentDocChunk] = []

        for s_idx, section in enumerate(sections):
            raw_text = "\n".join(section.lines).strip()
            if not raw_text:
                continue

            sub_chunks = self._split_section(raw_text)

            for c_idx, sub_text in enumerate(sub_chunks):
                sub_text = sub_text.strip()
                if not sub_text:
                    continue

                if not skip_scanning:
                    scan = secret_scanner.scan(sub_text)
                    if scan.should_skip:
                        continue
                    final_text = scan.redacted_text
                else:
                    final_text = sub_text

                cid = _chunk_id(relative_path, section.h1, section.h2,
                                 section.h3, s_idx, c_idx)
                checksum = _sha256(final_text)

                result.append(AgentDocChunk(
                    chunk_id=cid,
                    checksum=checksum,
                    relative_path=relative_path,
                    content=final_text,
                    h1=section.h1,
                    h2=section.h2,
                    h3=section.h3,
                    doc_priority=doc_priority,
                    required_on_session_start=required_on_session_start,
                    layer=layer,
                ))

        return result

    def _parse_sections(self, content: str) -> list[_Section]:
        """İçeriği başlık hiyerarşisine göre bölümlere ayırır."""
        sections: list[_Section] = []
        current = _Section()
        in_fence = False
        fence_marker = ""

        lines = content.splitlines(keepends=False)

        for line in lines:
            stripped = line.strip()

            if not in_fence:
                if stripped.startswith("```"):
                    in_fence = True
                    fence_marker = stripped[:3]
                    current.lines.append(line)
                    continue
            else:
                if stripped.startswith(fence_marker):
                    in_fence = False
                    fence_marker = ""
                current.lines.append(line)
                continue

            if re.match(r"^# [^#]", line):
                if current.lines or current.h1:
                    sections.append(current)
                current = _Section(h1=line.lstrip("# ").strip())
                continue

            if re.match(r"^## [^#]", line):
                if current.lines or current.h2:
                    sections.append(current)
                current = _Section(h1=current.h1, h2=line.lstrip("# ").strip())
                continue

            if re.match(r"^### [^#]", line):
                if current.lines or current.h3:
                    sections.append(current)
                current = _Section(
                    h1=current.h1,
                    h2=current.h2,
                    h3=line.lstrip("# ").strip(),
                )
                continue

            current.lines.append(line)

        if current.lines or current.h1:
            sections.append(current)

        return sections

    def _split_section(self, text: str) -> list[str]:
        """Bir bölümü config.chunk_max_chars sınırına göre parçalar."""
        if len(text) <= config.chunk_max_chars:
            return [text]

        blocks = self._extract_blocks(text)
        return self._pack_blocks(blocks)

    def _extract_blocks(self, text: str) -> list[str]:
        """Metni atomik bloklara böler."""
        blocks: list[str] = []
        lines = text.splitlines(keepends=False)
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.strip().startswith("```"):
                fence_lines = [line]
                marker = line.strip()[:3]
                i += 1
                while i < len(lines):
                    fence_lines.append(lines[i])
                    if lines[i].strip().startswith(marker) and i > (len(fence_lines) - 2):
                        i += 1
                        break
                    i += 1
                blocks.append("\n".join(fence_lines))
                continue

            if line.startswith("|"):
                table_lines = [line]
                i += 1
                while i < len(lines) and lines[i].startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                blocks.append(self._process_table(table_lines))
                continue

            # --- Düz paragraf / boş satır ---
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() != "" and not lines[i].startswith("|") and not lines[i].strip().startswith("```"):
                para_lines.append(lines[i])
                i += 1
            blocks.append("\n".join(para_lines))

        return [b for b in blocks if b.strip()]

    def _process_table(self, table_lines: list[str]) -> str:
        """
        Tablo config.chunk_max_chars'dan büyük değilse olduğu gibi döndürür.
        Büyükse başlık satırını her parçaya kopyalayarak satır gruplarına böler.
        """
        full = "\n".join(table_lines)
        if len(full) <= config.chunk_max_chars:
            return full

        # İlk 2 satır: başlık + separator (| --- | --- |)
        header = table_lines[:2]
        data_rows = table_lines[2:]

        parts: list[str] = []
        current_rows: list[str] = []

        for row in data_rows:
            probe = "\n".join(header + current_rows + [row])
            if len(probe) > config.chunk_max_chars and current_rows:
                parts.append("\n".join(header + current_rows))
                current_rows = [row]
            else:
                current_rows.append(row)

        if current_rows:
            parts.append("\n".join(header + current_rows))

        return "\n\n".join(parts)

    def _pack_blocks(self, blocks: list[str]) -> list[str]:
        """
        Atomik blokları toplayarak config.chunk_min_chars–config.chunk_max_chars
        aralığına sığan chunk'lar üretir.
        """
        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for block in blocks:
            blen = len(block)

            # Blok tek başına zaten MAX'ı aşıyorsa olduğu gibi al
            if blen > config.chunk_max_chars:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_len = 0
                chunks.append(block)
                continue

            # Mevcut birikime sığıyor mu?
            if current_len + blen + 2 <= config.chunk_max_chars:
                current_parts.append(block)
                current_len += blen + 2
            else:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                current_parts = [block]
                current_len = blen

        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

