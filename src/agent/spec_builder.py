"""
Spec Builder — TDAD'ın SPEC adımı için görev spesifikasyonu üretici.

Yapılandırılmış TaskSpec, görevin tüm yaşam döngüsünde rehber belgesidir:
  - LLM'e ne yapması gerektiğini bildirir
  - TEST adımına hangi test kriterlerini geçmesi gerektiğini söyler
  - CONTEXT adımına hangi dosyaları/sembolleri araması gerektiğini bildirir
  - REFLECT adımına başarı kriterlerini karşılayıp karşılamadığını ölçtürür
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TaskSpec:
    """Bir TDAD görevinin tam spesifikasyonu."""
    task_id:          str
    goal:             str
    collection:       str
    project_path:     str

    # Görev tipi: feature | bugfix | refactor | test | docs | security | other
    task_type:        str = "feature"

    # Etkilenen alanlar — CONTEXT adımı için arama girdisi
    affected_files:   list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    search_queries:   list[str] = field(default_factory=list)

    # Başarı kriterleri — REFLECT adımı için
    acceptance_criteria: list[str] = field(default_factory=list)

    # Test gereksinimleri — TEST adımı için
    test_hints:       list[str] = field(default_factory=list)
    fail_first:       bool = True   # TDAD: önce kırmızı test

    # Kısıtlar
    max_files_to_edit: int = 5
    language_hint:    str  = ""    # python | typescript | go | ...

    # Meta
    complexity_score: float = 0.5
    created_at:       float = field(default_factory=time.time)

    def to_prompt_block(self) -> str:
        """LLM promptuna eklenecek görev bloğu."""
        lines = [
            f"## Görev Spesifikasyonu",
            f"**Hedef:** {self.goal}",
            f"**Tip:** {self.task_type}",
            f"**Proje:** {self.project_path}",
            f"**Koleksiyon:** {self.collection}",
        ]

        if self.affected_files:
            lines.append(f"**Etkilenen dosyalar:** {', '.join(self.affected_files[:5])}")

        if self.acceptance_criteria:
            lines.append("\n**Başarı Kriterleri:**")
            for i, c in enumerate(self.acceptance_criteria, 1):
                lines.append(f"  {i}. {c}")

        if self.test_hints:
            lines.append("\n**Test İpuçları:**")
            for h in self.test_hints[:3]:
                lines.append(f"  - {h}")

        if self.fail_first:
            lines.append("\n> **TDAD:** Önce başarısız olan testi yaz, ardından kodu uygula.")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "TaskSpec":
        d = json.loads(data) if isinstance(data, str) else data
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SpecBuilder:
    """
    Kullanıcı hedefinden yapılandırılmış TaskSpec üretir.

    İki modda çalışır:
    1. heuristic_build(): LLM çağrısı olmadan, deterministik kural tabanlı
    2. llm_build():       LLM ile zenginleştirilmiş (model bağımlı)
    """

    # Görev tipi tespiti için anahtar kelimeler
    _TYPE_PATTERNS: dict[str, list[str]] = {
        "bugfix":   ["fix", "hata", "bug", "düzelt", "broken", "crash", "error",
                     "exception", "fail", "çalışmıyor", "kırık"],
        "refactor": ["refactor", "refaktör", "yeniden yaz", "rewrite", "temizle",
                     "clean", "reorganize", "soyutla", "abstract", "optimize"],
        "test":     ["test", "unit test", "integration test", "coverage", "kapsam",
                     "spec", "doğrula"],
        "security": ["security", "güvenlik", "vulnerability", "açık", "injection",
                     "auth", "ssl", "xss", "csrf", "sanitize"],
        "docs":     ["döküman", "document", "readme", "comment", "yorum", "açıkla",
                     "docstring"],
        "feature":  ["ekle", "add", "implement", "oluştur", "create", "yeni", "new",
                     "geliştir", "develop"],
    }

    def heuristic_build(
        self,
        task_id: str,
        goal: str,
        collection: str,
        project_path: str,
        complexity_score: float = 0.5,
        routing_decision=None,
    ) -> TaskSpec:
        """LLM olmadan deterministik kural tabanlı TaskSpec."""
        task_type = self._detect_type(goal)
        files     = self._extract_file_references(goal)
        symbols   = self._extract_symbols(goal)
        queries   = self._build_search_queries(goal, files, symbols)
        criteria  = self._derive_criteria(goal, task_type)
        hints     = self._derive_test_hints(goal, task_type, files)
        language  = self._detect_language(goal, files)

        spec = TaskSpec(
            task_id=task_id,
            goal=goal,
            collection=collection,
            project_path=project_path,
            task_type=task_type,
            affected_files=files,
            affected_symbols=symbols,
            search_queries=queries,
            acceptance_criteria=criteria,
            test_hints=hints,
            language_hint=language,
            complexity_score=complexity_score,
        )
        logger.debug(
            "SpecBuilder.heuristic_build: type=%s files=%s queries=%d",
            task_type, files, len(queries),
        )
        return spec

    async def llm_build(
        self,
        task_id: str,
        goal: str,
        collection: str,
        project_path: str,
        llm_client=None,
        model: str = "google/gemini-2.5-flash",
        base_url: Optional[str] = None,
        token_budget: int = 4000,
    ) -> TaskSpec:
        """LLM ile zenginleştirilmiş spec; LLM yoksa heuristic'e düşer."""
        base = self.heuristic_build(task_id, goal, collection, project_path)

        if llm_client is None:
            return base

        prompt = self._spec_prompt(goal, base)
        try:
            raw = await llm_client.complete(
                model=model,
                base_url=base_url,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=min(token_budget, 2000),
                temperature=0.1,
            )
            enriched = self._parse_llm_response(raw, base)
            logger.debug("SpecBuilder.llm_build: LLM spec zenginleştirildi")
            return enriched
        except Exception as exc:
            logger.warning("LLM spec build başarısız, heuristic kullanılıyor: %s", exc)
            return base

    # ── Yardımcı yöntemler ────────────────────────────────────────────────

    def _detect_type(self, goal: str) -> str:
        lower = goal.lower()
        scores: dict[str, int] = {}
        for typ, keywords in self._TYPE_PATTERNS.items():
            scores[typ] = sum(1 for kw in keywords if kw in lower)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "feature"

    def _extract_file_references(self, goal: str) -> list[str]:
        pattern = re.compile(r"\b[\w/.-]+\.(?:py|ts|tsx|js|go|java|rb|rs|cs|cpp|h)\b")
        return list(dict.fromkeys(pattern.findall(goal)))[:10]

    def _extract_symbols(self, goal: str) -> list[str]:
        # CamelCase veya snake_case fonksiyon/sınıf adı
        camel   = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")
        snake_fn= re.compile(r"\b[a-z][a-z0-9_]{2,}\b")
        results = camel.findall(goal) + snake_fn.findall(goal)
        # Sık görülen Türkçe kelimeleri filtrele
        stop = {"görev", "dosya", "proje", "kodda", "bunu", "için", "olan"}
        return [s for s in dict.fromkeys(results) if s.lower() not in stop][:8]

    def _build_search_queries(
        self, goal: str, files: list[str], symbols: list[str]
    ) -> list[str]:
        queries = [goal[:120]]
        queries.extend(f[:40] for f in files[:3])
        queries.extend(s for s in symbols[:3])
        return list(dict.fromkeys(queries))

    def _derive_criteria(self, goal: str, task_type: str) -> list[str]:
        base_criteria = [f"Görev tamamlanıyor: {goal[:80]}"]
        type_criteria = {
            "bugfix":   ["Hata artık tetiklenmiyor", "Mevcut testler geçiyor"],
            "refactor": ["Davranış değişmedi (testler hâlâ geçiyor)", "Kod daha okunabilir"],
            "test":     ["Test dosyası oluşturuldu", "Coverage %80+"],
            "security": ["Güvenlik açığı kapatıldı", "Güvenlik testi geçiyor"],
            "feature":  ["Yeni özellik çalışıyor", "Birim testi eklendi"],
        }
        return base_criteria + type_criteria.get(task_type, [])

    def _derive_test_hints(
        self, goal: str, task_type: str, files: list[str]
    ) -> list[str]:
        hints = []
        if task_type == "bugfix":
            hints.append("Hatayı reproduce eden bir test yaz, ardından kodu düzelt")
        elif task_type == "feature":
            hints.append("Yeni işlevselliği doğrulayan birim testi yaz")
        elif task_type == "security":
            hints.append("Güvenlik saldırı vektörünü modelleyen test yaz")
        if files:
            hints.append(f"Test dosyası: test_{files[0].replace('/', '_')}")
        return hints

    def _detect_language(self, goal: str, files: list[str]) -> str:
        for f in files:
            if f.endswith(".py"):      return "python"
            if f.endswith((".ts", ".tsx")): return "typescript"
            if f.endswith(".go"):      return "go"
            if f.endswith(".java"):    return "java"
            if f.endswith(".rs"):      return "rust"
        # Goal'dan tahmin
        lower = goal.lower()
        if "python" in lower: return "python"
        if "typescript" in lower or "react" in lower: return "typescript"
        if "golang" in lower or " go " in lower: return "go"
        return ""

    def _spec_prompt(self, goal: str, base: TaskSpec) -> str:
        return f"""Aşağıdaki yazılım geliştirme görevini analiz et ve JSON formatında bir spesifikasyon üret.

Görev: {goal}
Tespit edilen tip: {base.task_type}
Etkilenen dosyalar: {base.affected_files}

Lütfen aşağıdaki JSON formatında yanıt ver:
{{
  "acceptance_criteria": ["kriter1", "kriter2"],
  "test_hints": ["ipucu1", "ipucu2"],
  "affected_symbols": ["Sembol1", "sembol2"],
  "search_queries": ["sorgu1", "sorgu2"],
  "language_hint": "python"
}}

Sadece JSON döndür, açıklama ekleme."""

    def _parse_llm_response(self, raw: str, base: TaskSpec) -> TaskSpec:
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return base
            data = json.loads(match.group())
            if data.get("acceptance_criteria"):
                base.acceptance_criteria = data["acceptance_criteria"]
            if data.get("test_hints"):
                base.test_hints = data["test_hints"]
            if data.get("affected_symbols"):
                base.affected_symbols = data["affected_symbols"]
            if data.get("search_queries"):
                base.search_queries = list(dict.fromkeys(
                    base.search_queries + data["search_queries"]
                ))[:6]
            if data.get("language_hint"):
                base.language_hint = data["language_hint"]
        except Exception as exc:
            logger.debug("LLM spec parse hatası: %s", exc)
        return base


# Singleton
_builder: Optional[SpecBuilder] = None


def get_spec_builder() -> SpecBuilder:
    global _builder
    if _builder is None:
        _builder = SpecBuilder()
    return _builder
