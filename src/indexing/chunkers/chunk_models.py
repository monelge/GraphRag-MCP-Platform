from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SemanticMeta:
    """
    LLM tarafından üretilen anlamsal meta veri.
    Neden ayrı bir dataclass? Semantic enrichment opsiyoneldir;
    bazı chunk'lar bu bilgiye sahip olmayabilir.
    """
    purpose: Optional[str] = None    # "JWT token doğrular, kullanıcı kimliğini döner"
    domain: Optional[str] = None     # auth | payment | inventory | common
    keywords: list[str] = field(default_factory=list)  # ["jwt", "bcrypt", "token"]


@dataclass
class CodeChunk:
    chunk_id: str          # SHA256 tabanlı benzersiz kimlik
    file_path: str         # Kaynak dosyanın yolu
    language: str          # python / typescript / csharp vb.
    chunk_type: str        # function | class | module | method
    name: str              # Fonksiyon ya da sınıf adı
    code: str              # Ham kaynak kodu
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    parent_class: Optional[str] = None          # Bir metotsa ait olduğu sınıf
    imports: list[str] = field(default_factory=list)  # Modül bağımlılıkları
    calls: list[str] = field(default_factory=list)    # Fonksiyon/Metot çağrıları
    bases: list[str] = field(default_factory=list)    # Kalıtım/Arayüz (Phase 2)
    config_keys: list[str] = field(default_factory=list) # Kullanılan config/env (Phase 2)
    semantic_meta: Optional[SemanticMeta] = None  # LLM ile doldurulur (opsiyonel)
    
    # Faz 2: Provenance & Metadata
    project: str = "default"
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    indexed_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self):
        """Storage katmanları için dictionary formatına dönüştürür."""
        data = {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "language": self.language,
            "chunk_type": self.chunk_type,
            "name": self.name,
            "code": self.code,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "docstring": self.docstring,
            "parent_class": self.parent_class,
            "imports": self.imports,
            "calls": self.calls,
            "bases": self.bases,
            "config_keys": self.config_keys,
            "project": self.project,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "indexed_at": self.indexed_at
        }
        if self.semantic_meta:
            data["semantic_meta"] = {
                "purpose": self.semantic_meta.purpose,
                "domain": self.semantic_meta.domain,
                "keywords": self.semantic_meta.keywords
            }
        return data


@dataclass
class AgentDocChunk:
    """
    .agent/ dizinindeki markdown dokümantasyon dosyalarından üretilen chunk.

    Neden CodeChunk'tan ayrı?
      Markdown dokümanlarının metadata şeması (header hierarchy, doc_priority,
      layer gibi policy alanları) kod chunk'larından tamamen farklıdır.
      Aynı Qdrant collection'da yaşarlar ama source_type='agent_doc' ile
      kod chunk'larından (source_type='source_code') ayrılır.

    chunk_id hesabı: sha256(relative_path|h1|h2|h3|section_idx|chunk_idx)
      Neden content'e bağlı değil? İçerik değişince checksum değişir — bu yeterli.
      chunk_id, konuma bağlı stabil bir kimlik olduğundan incremental sync'de
      aynı pozisyondaki chunk'ı güncellemek için kullanılır.

    checksum hesabı: sha256(content)
      Saf içerik hash'i. Değişmemişse embedding yeniden üretilmez.
    """
    chunk_id: str                       # Konum tabanlı stabil kimlik (SHA256 hex)
    checksum: str                       # İçerik hash'i — incremental sync için
    relative_path: str                  # Örn: ".agent/backend.md"
    content: str                        # Ham markdown içerik
    h1: str = ""
    h2: str = ""
    h3: str = ""
    doc_priority: str = "normal"        # critical | high | normal
    required_on_session_start: bool = False
    layer: str = ""                     # backend | frontend | security | rules | entity | init | state
    source_type: str = "agent_doc"      # Daima "agent_doc" — search_code filtresi için
    schema_version: int = 1
    is_deleted: bool = False
    updated_at: str = field(default_factory=_utc_now_iso)
    cross_refs: list[str] = field(default_factory=list)  # İleride Context Builder kullanır
