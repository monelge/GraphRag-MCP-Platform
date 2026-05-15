from __future__ import annotations

from pathlib import Path

from src.handlers.context import AppContext
from src.handlers.indexing_handler import IndexingHandler
from src.indexing.pipelines.project_intelligence import (
    build_project_profile,
    format_profile,
    sync_project_intelligence,
)


class ControlHandler:
    """Registry, control plane ve impact analizi araçlarının uygulama katmanı."""

    def __init__(self, ctx: AppContext, indexing: IndexingHandler):
        self.ctx = ctx
        self.indexing = indexing

    async def register_project(
        self,
        project_path: str,
        collection: str = "",
        index_code: bool = True,
        index_docs: bool = True,
        batch_size: int = 32,
    ) -> str:
        """Projeyi registry'ye kaydeder ve isteğe bağlı indeksler."""
        profile = build_project_profile(project_path, collection=collection)
        self.ctx.registry.upsert(profile)

        results = [format_profile(profile)]
        if index_code:
            results.append(
                await self.indexing.index_project(
                    project_path=project_path,
                    collection=profile.collection,
                    batch_size=batch_size,
                )
            )
        else:
            await self.indexing.sync_project_foundation(project_path, profile.collection)

        if index_docs:
            agent_dir = Path(project_path).resolve() / ".agent"
            if agent_dir.exists():
                results.append(await self.indexing.index_agent_docs(project_path=project_path))
            else:
                results.append("ℹ️ .agent/ dizini bulunmadı; agent doc indeksleme atlandı.")

        return "\n\n".join(results)

    async def list_projects(self) -> str:
        """Registry'deki kayıtlı projeleri listeler."""
        profiles = self.ctx.registry.list_profiles()
        if not profiles:
            return "ℹ️ Henüz kayıtlı proje bulunmuyor."

        lines = ["## Kayıtlı Projeler\n"]
        for profile in profiles:
            lines.append(
                f"### `{profile.collection}`\n"
                f"- Proje: {profile.project_name}\n"
                f"- Path: `{profile.project_path}`\n"
                f"- Diller: {', '.join(profile.languages) or '-'}\n"
                f"- Frameworkler: {', '.join(profile.frameworks) or '-'}\n"
                f"- Modüller: {', '.join(profile.module_roots[:6]) or '-'}\n"
            )
        return "\n".join(lines)

    async def summarize_repository(self, project_path: str, collection: str = "") -> str:
        """Repo özetini üretip registry'yi günceller."""
        profile = await sync_project_intelligence(
            project_path,
            collection=collection,
            redis_store=self.ctx.redis,
            neo4j_store=self.ctx.neo4j,
        )
        self.ctx.registry.upsert(profile)
        return format_profile(profile)

    async def get_control_plane_stats(self) -> str:
        """Model gateway istatistiklerini ve DB'den kalıcı LLM/retrieval/audit özetini döndürür."""
        stats = self.ctx.model_gateway.get_stats()
        lines = [
            "## 🕹️ Control Plane — Model Gateway Stats",
            f"- **Toplam Çağrı:** {stats['total_calls']}",
            f"- **Toplam Token (oturum):** {stats['total_tokens']}",
            f"- **Top. Gecikme:** {stats['total_latency_ms'] / 1000:.1f}s",
            "\n### Model Bazlı Detaylar (oturum içi):",
        ]
        for model, model_stats in stats["per_model_stats"].items():
            lines.append(
                f"- **{model}:** {model_stats['calls']} çağrı | {model_stats['tokens']} token | {model_stats['avg_latency']:.0f}ms avg"
            )

        # ── Kalıcı DB istatistikleri ──────────────────────────────────────────
        # LLM token kullanımı
        db_rows = await self.ctx.postgres.get_llm_usage_stats(days=7)
        if db_rows:
            lines.append("\n### 📊 DB — Son 7 Gün LLM Token Kullanımı:")
            for row in db_rows:
                lines.append(
                    f"- **{row['model']}:** {row['calls']} çağrı | "
                    f"prompt={row['prompt_tokens']} | completion={row['completion_tokens']} | "
                    f"toplam={row['total_tokens']} | avg={row['avg_latency_ms']}ms"
                )

        # Retrieval istatistikleri
        retrieval_rows = await self.ctx.postgres.get_retrieval_stats(days=7)
        if retrieval_rows:
            lines.append("\n### 🔍 DB — Son 7 Gün Retrieval İstatistikleri:")
            for row in retrieval_rows:
                cache_pct = int(row["cache_hits"] / row["calls"] * 100) if row["calls"] else 0
                fail_pct = int(row["answerability_fails"] / row["calls"] * 100) if row["calls"] else 0
                lines.append(
                    f"- **{row['collection']}** `{row['query_type'] or '-'}`: "
                    f"{row['calls']} sorgu | "
                    f"cache={row['cache_hits']} (%{cache_pct}) | "
                    f"yetersiz={row['answerability_fails']} (%{fail_pct}) | "
                    f"avg_latency={row['avg_latency_ms']}ms | "
                    f"avg_hit={row['avg_hit_count']:.1f} | "
                    f"avg_score={row['avg_top1_score']:.3f}"
                )

        # Audit event özeti
        audit_data = await self.ctx.postgres.get_audit_stats(days=7)
        if audit_data.get("summary"):
            lines.append("\n### 🛡️ DB — Son 7 Gün Audit Olayları:")
            for row in audit_data["summary"]:
                lines.append(f"- **{row['event_type']}:** {row['count']} olay | son: {row['last_seen']}")
        if audit_data.get("recent"):
            lines.append("\n#### Son 5 Audit Kaydı:")
            for row in audit_data["recent"]:
                lines.append(
                    f"  - `{row['event_type']}` | {row['collection'] or '-'} | "
                    f"{(row['summary'] or '')[:60]} | {row['created_at']}"
                )

        return "\n".join(lines)

    async def analyze_change_impact(
        self,
        project_path: str,
        changed_paths: list[str],
        collection: str = "",
    ) -> str:
        """Neo4j graph üzerinden değişiklik etki analizi yapar."""
        collection = collection or IndexingHandler.project_collection_name(project_path)
        normalized, rejected = IndexingHandler.normalize_changed_files(
            project_path,
            changed_paths,
            IndexingHandler.SUPPORTED_SOURCE_EXTENSIONS,
            IndexingHandler.EXCLUDE_DIRS,
        )
        if not normalized:
            return "⚠️ Analiz edilecek geçerli bir dosya yolu bulunamadı."

        results = await self.ctx.impact_analyzer.analyze(collection, normalized)
        lines = [
            f"## 🔍 Değişiklik Etki Analizi — {collection}",
            f"**Genel Durum:** {results['summary']}",
            f"**Etkilenen Dosya Sayısı:** {len(results['total_affected_files'])}",
            "",
        ]
        for path, data in results["files"].items():
            rel_path = Path(path).name
            lines.append(f"### 📄 `{rel_path}` (Etki Puanı: {data['score']})")
            if data["entities"]:
                lines.append(
                    "**İçerik:** "
                    + ", ".join(
                        f"`{entity['name']}` ({entity['type'] or 'entity'})"
                        for entity in data["entities"][:10]
                    )
                )
            if data["callers"]:
                lines.append("\n**Etkilenen Çağrıcılar (Callers):**")
                for caller in data["callers"][:12]:
                    dist_note = " (doğrudan)" if caller["distance"] == 1 else f" ({caller['distance']} seviye)"
                    lines.append(
                        f"  - `{caller['name']}`{dist_note} → `{Path(caller.get('file_path', '')).name}`"
                    )
            else:
                lines.append("\n**Dış çağrıcı bulunamadı.**")
            if data["dependencies"]:
                lines.append("\n**Bağımlılıklar (Uses):**")
                for dependency in data["dependencies"][:8]:
                    lines.append(f"  - `{dependency['name']}`")
            lines.append("")

        if rejected:
            lines.append("\n---\n**Atlanan Yollar:** " + ", ".join(f"`{path}`" for path in rejected[:10]))
        return "\n".join(lines)
