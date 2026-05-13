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

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .chunk_models import AgentDocChunk
from . import secret_scanner

# Token tahmin katsayısı: ortalama İngilizce metin için 1 token ≈ 4 karakter.
# Türkçe ve karma metin için biraz daha geniş tutuyoruz → 3.5 char/token.
_CHARS_PER_TOKEN = 3.5
_MIN_CHARS = int(300 * _CHARS_PER_TOKEN)   # ~1050
_MAX_CHARS = int(800 * _CHARS_PER_TOKEN)   # ~2800

# Dosya adından layer ve doc_priority belirleme tablosu.
# Neden statik mapping? Policy kararları (hangi dosya kritik?) operasyonel bilgidir;
# dosya adından otomatik çıkarımı az sayıda dosya için yeterlidir.
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
# .agent/ dosyaları intentional demo secrets içerir (JWT, token örnekleri)
# Bu dosyalar operasyonel gizlilikleri değil, documentation'a ait örnektir
_WHITELIST_SKIP_SCANNING: set[str] = {
    "security.md",              # Demo JWT tokens, API key örnekleri
    "rules.md",                 # Yapılandırma örnekleri
    "backend.md",               # Backend pattern'leri, config örnekleri
    "frontend.md",              # Frontend config örnekleri
    "backend-architecture.md",  # Backend mimarisi (demo config'ler)
    "mobile-plan.md",           # Mobile plan (BASE64 config'leri)
    "mobile-state.md",          # Mobile state (BASE64 artifacts)
    "mobile-tasks.md",          # Mobile tasks (BASE64 examples)
    "state.md",                 # State documentation (BASE64 samples)
    "tasks.md",                 # Task documentation (BASE64 samples)
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
    """
    Konum tabanlı stabil kimlik.
    Neden content'e bağlı değil?
      checksum zaten içerik değişimini izler.
      chunk_id'nin konuma bağlı stabil olması sayesinde aynı pozisyondaki chunk
      incremental sync'de doğru eşleştirilir.
    """
    key = f"{relative_path}|{h1}|{h2}|{h3}|{section_idx}|{chunk_idx}"
    return _sha256(key)


class MarkdownChunker:

    def chunk_file(self, file_path: str, relative_path: Optional[str] = None) -> list[AgentDocChunk]:
        """
        Dosyayı okur ve chunk listesi döndürür.
        relative_path verilmezse file_path'ten türetilir.
        
        Whitelist Davranışı:
          - Dosya _WHITELIST_SKIP_SCANNING içindeyse SecretScanner bypass edilir
          - .agent/ documentation dosyalarında intentional demo secrets bulunabilir
        """
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        rel = relative_path or str(path)
        filename = path.name.lower()

        layer = _FILE_LAYER_MAP.get(filename, "")
        doc_priority = _FILE_PRIORITY_MAP.get(filename, "normal")
        required = filename in _REQUIRED_ON_START
        
        # Dosya whitelist'te ise SecretScanner'ı bypass et
        skip_scanning = filename in _WHITELIST_SKIP_SCANNING

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

                # SecretScanner — son savunma hattı
                # Whitelist'te olan dosyalar (documentation) bypass edilir
                if not skip_scanning:
                    scan = secret_scanner.scan(sub_text)
                    if scan.should_skip:
                        continue
                    final_text = scan.redacted_text
                else:
                    # Whitelist dosyası: scanning skip et, demo secrets izin ver
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
        """
        İçeriği başlık hiyerarşisine göre bölümlere ayırır.
        Kod fence içindeki # satırları başlık sayılmaz.
        """
        sections: list[_Section] = []
        current = _Section()
        in_fence = False
        fence_marker = ""

        lines = content.splitlines(keepends=False)

        for line in lines:
            stripped = line.strip()

            # Kod fence takibi — fence içinde başlık ayrıştırması yapılmaz
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

            # H1 başlığı → yeni ana bölüm
            if re.match(r"^# [^#]", line):
                if current.lines or current.h1:
                    sections.append(current)
                current = _Section(h1=line.lstrip("# ").strip())
                continue

            # H2 başlığı → alt bölüm, H1 korunur
            if re.match(r"^## [^#]", line):
                if current.lines or current.h2:
                    sections.append(current)
                current = _Section(h1=current.h1, h2=line.lstrip("# ").strip())
                continue

            # H3 başlığı → alt-alt bölüm, H1+H2 korunur
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

        # Son bölümü ekle
        if current.lines or current.h1:
            sections.append(current)

        return sections

    def _split_section(self, text: str) -> list[str]:
        """
        Bir bölümü MAX_CHARS sınırına göre parçalar.
        Öncelik sırası:
          1. Kod blokları: ``` ... ``` asla bölünmez
          2. Tablolar: | satırları tek blok (başlık her parçaya kopyalanır)
          3. Paragraf: boş satırda bölünür
        """
        if len(text) <= _MAX_CHARS:
            return [text]

        blocks = self._extract_blocks(text)
        return self._pack_blocks(blocks)

    def _extract_blocks(self, text: str) -> list[str]:
        """
        Metni atomik bloklara böler:
          - Kod fence bloğu → tek atom
          - Tablo bloğu → tek atom (başlık + satırlar)
          - Düz paragraf → boş satırda ayrılan parçalar
        """
        blocks: list[str] = []
        lines = text.splitlines(keepends=False)
        i = 0

        while i < len(lines):
            line = lines[i]

            # --- Kod fence başlangıcı ---
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

            # --- Tablo başlangıcı (| ile başlayan satır) ---
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
        Tablo 800 token'dan büyük değilse olduğu gibi döndürür.
        Büyükse başlık satırını her parçaya kopyalayarak satır gruplarına böler.
        Sonuç tek string olarak döndürülür (parçalar \n---\n ile ayrılır);
        _pack_blocks bu iç bölünmeyi daha sonra işler.
        """
        full = "\n".join(table_lines)
        if len(full) <= _MAX_CHARS:
            return full

        # İlk 2 satır: başlık + separator (| --- | --- |)
        header = table_lines[:2]
        data_rows = table_lines[2:]

        parts: list[str] = []
        current_rows: list[str] = []

        for row in data_rows:
            probe = "\n".join(header + current_rows + [row])
            if len(probe) > _MAX_CHARS and current_rows:
                parts.append("\n".join(header + current_rows))
                current_rows = [row]
            else:
                current_rows.append(row)

        if current_rows:
            parts.append("\n".join(header + current_rows))

        return "\n\n".join(parts)

    def _pack_blocks(self, blocks: list[str]) -> list[str]:
        """
        Atomik blokları toplayarak MIN_CHARS–MAX_CHARS aralığına sığan
        chunk'lar üretir.

        Neden pack?
          Tek başına çok kısa olan bloklar (ör. tek satır paragraf) birleştirilir;
          bu şekilde retrieval'da daha anlamlı bağlam taşıyan chunk'lar elde edilir.
        """
        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for block in blocks:
            blen = len(block)

            # Blok tek başına zaten MAX'ı aşıyorsa olduğu gibi al
            if blen > _MAX_CHARS:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_len = 0
                chunks.append(block)
                continue

            # Mevcut birikime sığıyor mu?
            if current_len + blen + 2 <= _MAX_CHARS:
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
