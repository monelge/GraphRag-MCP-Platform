"""
Impact Analysis — Hibrit etki skoru hesaplayıcı.

Hibrit skor: 0.4×call_graph + 0.3×dependency_graph + 0.2×pagerank + 0.1×git_co_change

analyze_change_impact MCP aracını çağırır; yoksa statik fallback kullanır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

W_CALL   = float(os.getenv("IMPACT_W_CALL_GRAPH",  "0.40"))
W_DEP    = float(os.getenv("IMPACT_W_DEP_GRAPH",   "0.30"))
W_PR     = float(os.getenv("IMPACT_W_PAGERANK",    "0.20"))
W_CO     = float(os.getenv("IMPACT_W_CO_CHANGE",   "0.10"))


@dataclass
class FileImpact:
    file_path:   str
    score:       float       # 0.0–1.0 hibrit skor
    call_graph:  float = 0.0
    dep_graph:   float = 0.0
    pagerank:    float = 0.0
    co_change:   float = 0.0
    risk:        str   = "low"   # low | medium | high
    change_type: str   = "modified"

    @classmethod
    def compute(
        cls,
        file_path: str,
        call_graph:  float = 0.0,
        dep_graph:   float = 0.0,
        pagerank:    float = 0.0,
        co_change:   float = 0.0,
        change_type: str = "modified",
    ) -> "FileImpact":
        score = (W_CALL*call_graph + W_DEP*dep_graph + W_PR*pagerank + W_CO*co_change)
        score = round(min(max(score, 0.0), 1.0), 4)
        risk  = "high" if score >= 0.7 else ("medium" if score >= 0.4 else "low")
        return cls(
            file_path=file_path,
            score=score,
            call_graph=call_graph,
            dep_graph=dep_graph,
            pagerank=pagerank,
            co_change=co_change,
            risk=risk,
            change_type=change_type,
        )


@dataclass
class ImpactReport:
    changed_files: list[str]
    affected:      list[FileImpact] = field(default_factory=list)
    summary:       str = ""
    high_risk_count: int = 0

    def top_files(self, n: int = 5) -> list[FileImpact]:
        return sorted(self.affected, key=lambda f: f.score, reverse=True)[:n]

    def to_summary_text(self) -> str:
        top = self.top_files(5)
        lines = [f"Etkilenen {len(self.affected)} dosya (yüksek risk: {self.high_risk_count}):"]
        for f in top:
            lines.append(f"  {f.file_path} → skor={f.score:.2f} risk={f.risk}")
        return "\n".join(lines)


class ImpactAnalyzer:
    """
    Değişen dosyaların etki analizini yapar.

    mcp_handler varsa analyze_change_impact aracını çağırır;
    yoksa statik fallback (uzantı + satır sayısı tahmini) kullanır.
    """

    def __init__(self, mcp_handler=None) -> None:
        self._mcp = mcp_handler

    async def analyze(
        self,
        project_path: str,
        changed_paths: list[str],
        collection: str,
    ) -> ImpactReport:
        if not changed_paths:
            return ImpactReport(changed_files=[])

        if self._mcp:
            try:
                raw = await self._mcp.analyze_change_impact(
                    project_path=project_path,
                    changed_paths=changed_paths,
                    collection=collection,
                )
                return self._parse_mcp_result(raw, changed_paths)
            except Exception as exc:
                logger.warning("MCP impact analiz hatası, fallback: %s", exc)

        return self._static_fallback(changed_paths, project_path)

    def _parse_mcp_result(self, raw: dict | list, changed: list[str]) -> ImpactReport:
        affected: list[FileImpact] = []

        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("affected_files", raw.get("files", raw.get("impacts", [])))

        for item in items:
            if isinstance(item, dict):
                fp = item.get("file_path", item.get("path", "unknown"))
                fi = FileImpact.compute(
                    file_path=fp,
                    call_graph=float(item.get("call_graph_score", 0)),
                    dep_graph= float(item.get("dependency_score",  0)),
                    pagerank=  float(item.get("pagerank_score",    0)),
                    co_change= float(item.get("co_change_score",   0)),
                    change_type=item.get("change_type", "modified"),
                )
                affected.append(fi)

        # Belirtilen ama sonuçta olmayan dosyaları ekle
        existing = {f.file_path for f in affected}
        for fp in changed:
            if fp not in existing:
                affected.append(FileImpact.compute(fp, dep_graph=0.3))

        high_risk = sum(1 for f in affected if f.risk == "high")
        report = ImpactReport(
            changed_files=changed,
            affected=affected,
            high_risk_count=high_risk,
        )
        report.summary = report.to_summary_text()
        return report

    def _static_fallback(self, changed: list[str], project_path: str) -> ImpactReport:
        """Dosya uzantısına ve satır sayısına göre basit skor tahmin eder."""
        affected: list[FileImpact] = []
        proj = Path(project_path)

        for fp in changed:
            full = proj / fp
            lines = 0
            try:
                lines = sum(1 for _ in full.open(errors="ignore"))
            except Exception:
                pass

            # Uzantıya göre temel etki skoru
            ext = Path(fp).suffix.lower()
            base_dep = {
                ".py":   0.5, ".ts": 0.5, ".tsx": 0.4, ".go": 0.5,
                ".java": 0.5, ".sql": 0.6, ".yaml": 0.3, ".json": 0.2,
                ".md":   0.0, ".txt": 0.0,
            }.get(ext, 0.3)

            # Satır sayısı → call_graph proxy
            call_proxy = min(lines / 500, 1.0) if lines else 0.0

            affected.append(FileImpact.compute(
                file_path=fp,
                call_graph=call_proxy,
                dep_graph=base_dep,
                co_change=0.1,
            ))

        high_risk = sum(1 for f in affected if f.risk == "high")
        report = ImpactReport(
            changed_files=changed,
            affected=affected,
            high_risk_count=high_risk,
        )
        report.summary = report.to_summary_text()
        return report


# Singleton
_analyzer: Optional[ImpactAnalyzer] = None


def get_impact_analyzer(mcp_handler=None) -> ImpactAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ImpactAnalyzer(mcp_handler)
    elif mcp_handler and _analyzer._mcp is None:
        _analyzer._mcp = mcp_handler
    return _analyzer
