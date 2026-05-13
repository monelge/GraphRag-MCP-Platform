from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

from src.indexing.chunkers.chunk_models import CodeChunk
from src.indexing.embedders.dense_embedder import DenseEmbedder
from src.indexing.embedders.sparse_embedder import SparseEmbedder
from src.shared.project_registry import ProjectProfile
from src.storage.qdrant_store import QdrantStore
from src.storage.redis_store import RedisStore


_EXT_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
}

_SUMMARY_SOURCE = "repo_summary"
_SUMMARY_KINDS = ("project_profile", "repo_summary", "module_summary")
_EXCLUDE_DIRS = {"node_modules", "bin", "obj", "dist", ".next", "__pycache__", ".venv", "venv", "migrations", ".git"}


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _collection_name(project_path: str, collection: str = "") -> str:
    return collection or Path(project_path).resolve().name.replace(" ", "_")


def _iter_source_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if _EXCLUDE_DIRS.intersection(path.parts):
            continue
        if path.suffix in _EXT_LANGUAGE:
            files.append(path)
    return files


def _discover_frameworks(project_root: Path) -> tuple[list[str], list[str], list[str]]:
    frameworks: list[str] = []
    package_managers: list[str] = []
    entrypoints: list[str] = []

    if list(project_root.glob("*.sln")) or list(project_root.glob("*.slnx")) or (project_root / "global.json").exists():
        frameworks.append(".NET")
        package_managers.append("nuget")
    if list(project_root.rglob("package.json")):
        frameworks.append("Node.js")
        package_managers.append("npm")
    if list(project_root.rglob("angular.json")):
        frameworks.append("Angular")
    if list(project_root.rglob("pubspec.yaml")):
        frameworks.append("Flutter")
        package_managers.append("pub")
    if list(project_root.rglob("requirements.txt")) or list(project_root.rglob("pyproject.toml")):
        frameworks.append("Python")
        package_managers.append("pip")
    if (project_root / "docker-compose.yml").exists() or (project_root / "Dockerfile").exists():
        frameworks.append("Docker")

    for candidate in ("Program.cs", "main.py", "manage.py", "app.py", "main.ts", "main.dart"):
        if list(project_root.rglob(candidate)):
            entrypoints.append(candidate)

    return sorted(set(frameworks)), sorted(set(package_managers)), sorted(set(entrypoints))


def _discover_module_roots(project_root: Path, source_files: list[Path]) -> list[str]:
    preferred_roots = []
    for candidate in ("backend/src", "frontend", "src", "apps", "services"):
        path = project_root / candidate
        if path.exists():
            preferred_roots.append(path)

    modules: Counter[str] = Counter()
    for file_path in source_files:
        rel = file_path.relative_to(project_root)
        if rel.parts and rel.parts[0] in {"backend", "frontend", "src", "apps", "services"}:
            key = "/".join(rel.parts[: min(3, len(rel.parts) - 1)])
        else:
            key = rel.parts[0] if rel.parts else "."
        modules[key] += 1

    selected = [name for name, count in modules.most_common(12) if count >= 2]
    if preferred_roots:
        preferred_names = [str(p.relative_to(project_root)) for p in preferred_roots]
        for name in reversed(preferred_names):
            if name not in selected:
                selected.insert(0, name)
    return selected[:12]


def build_project_profile(project_path: str, collection: str = "") -> ProjectProfile:
    project_root = Path(project_path).resolve()
    coll = _collection_name(project_path, collection)
    source_files = _iter_source_files(project_root)
    lang_counter = Counter(_EXT_LANGUAGE[p.suffix] for p in source_files if p.suffix in _EXT_LANGUAGE)
    frameworks, package_managers, entrypoints = _discover_frameworks(project_root)
    module_roots = _discover_module_roots(project_root, source_files)

    summary = (
        f"{project_root.name} projesi {len(source_files)} kaynak dosya içeriyor. "
        f"Diller: {', '.join(lang_counter.keys()) or 'bilinmiyor'}. "
        f"Frameworkler: {', '.join(frameworks) or 'tespit edilemedi'}. "
        f"Öne çıkan modüller: {', '.join(module_roots[:6]) or 'yok'}."
    )

    return ProjectProfile(
        project_name=project_root.name,
        collection=coll,
        project_path=str(project_root),
        languages=list(lang_counter.keys()),
        frameworks=frameworks,
        package_managers=package_managers,
        module_roots=module_roots,
        entrypoints=entrypoints,
        summary=summary,
        indexed_at=time.time(),
    )


def build_summary_chunks(profile: ProjectProfile) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    profile_payload = {
        "frameworks": ", ".join(profile.frameworks) or "tespit edilmedi",
        "languages": ", ".join(profile.languages) or "tespit edilmedi",
        "package_managers": ", ".join(profile.package_managers) or "tespit edilmedi",
        "entrypoints": ", ".join(profile.entrypoints) or "tespit edilmedi",
    }
    project_text = (
        f"Proje: {profile.project_name}\n"
        f"Koleksiyon: {profile.collection}\n"
        f"Path: {profile.project_path}\n"
        f"Diller: {profile_payload['languages']}\n"
        f"Frameworkler: {profile_payload['frameworks']}\n"
        f"Paket yöneticileri: {profile_payload['package_managers']}\n"
        f"Entrypoint'ler: {profile_payload['entrypoints']}\n"
        f"Özet: {profile.summary}"
    )
    chunks.append(
        CodeChunk(
            chunk_id=_stable_id(profile.collection, "project_profile"),
            file_path=f"summary://{profile.collection}/project_profile",
            language="markdown",
            chunk_type="project_profile",
            name=f"{profile.project_name} Project Profile",
            code=project_text,
            start_line=0,
            end_line=0,
        )
    )

    repo_text = (
        f"{profile.project_name} repository summary.\n"
        f"Module roots: {', '.join(profile.module_roots) or 'yok'}.\n"
        f"Bu proje için architecture, onboarding ve impact analysis sorgularında ilk bağlam olarak kullanılmalıdır."
    )
    chunks.append(
        CodeChunk(
            chunk_id=_stable_id(profile.collection, "repo_summary"),
            file_path=f"summary://{profile.collection}/repo_summary",
            language="markdown",
            chunk_type="repo_summary",
            name=f"{profile.project_name} Repository Summary",
            code=repo_text,
            start_line=0,
            end_line=0,
        )
    )

    for module_root in profile.module_roots:
        chunks.append(
            CodeChunk(
                chunk_id=_stable_id(profile.collection, "module_summary", module_root),
                file_path=f"summary://{profile.collection}/module/{module_root}",
                language="markdown",
                chunk_type="module_summary",
                name=f"{module_root} Module Summary",
                code=(
                    f"Modül yolu: {module_root}\n"
                    f"Proje: {profile.project_name}\n"
                    f"Koleksiyon: {profile.collection}\n"
                    f"Bu modül {profile.project_name} içinde önemli bir kök klasördür ve architecture sorgularında öncelikli bağlamdır."
                ),
                start_line=0,
                end_line=0,
            )
        )

    return chunks


from src.storage.neo4j_store import Neo4jStore


async def generate_global_architecture_summary(collection: str, neo4j_store: Neo4jStore) -> str:
    """
    Neo4j üzerindeki modüller arası CALLS ve DEPENDS_ON ilişkilerini sorgulayarak
    projenin yüksek seviyeli mimari özetini çıkarır.
    """
    query = """
    MATCH (m1:Module {collection: $coll})-[r:CALLS|DEPENDS_ON]->(m2:Module {collection: $coll})
    RETURN m1.name AS from_mod, type(r) AS rel, m2.name AS to_mod, count(r) AS weight
    ORDER BY weight DESC
    LIMIT 20
    """
    records = await neo4j_store.execute_query(query, {"coll": collection})
    if not records:
        return "Modüller arası belirgin bir bağımlılık zinciri tespit edilemedi."

    lines = ["## Global Mimari Etkileşim Özeti", "Önemli modül etkileşimleri ve bağımlılık zinciri:"]
    for rec in records:
        from_mod = Path(rec["from_mod"]).name
        to_mod = Path(rec["to_mod"]).name
        lines.append(f"- `{from_mod}` --[{rec['rel']} (x{rec['weight']})]--> `{to_mod}`")
    
    return "\n".join(lines)


async def sync_project_intelligence(
    project_path: str,
    collection: str = "",
    redis_store: RedisStore | None = None,
    neo4j_store: Neo4jStore | None = None,
) -> ProjectProfile:
    profile = build_project_profile(project_path, collection)
    store = QdrantStore(collection=profile.collection)
    await store.ensure_collection()

    chunks = build_summary_chunks(profile)
    
    # Global Mimari Özeti ekle (eğer neo4j varsa)
    if neo4j_store:
        arch_text = await generate_global_architecture_summary(profile.collection, neo4j_store)
        chunks.append(
            CodeChunk(
                chunk_id=_stable_id(profile.collection, "global_architecture"),
                file_path=f"summary://{profile.collection}/global_architecture",
                language="markdown",
                chunk_type="repo_summary",
                name="Global Architecture Summary",
                code=arch_text,
                start_line=0,
                end_line=0,
            )
        )

    dense = DenseEmbedder(redis_store=redis_store)
    sparse = SparseEmbedder()
    texts = [chunk.code for chunk in chunks]
    dense_vecs = await dense.embed_batch(texts)
    sparse_vecs = list(sparse.embed_batch(texts))
    await store.upsert_chunks(
        chunks,
        dense_vecs,
        sparse_vecs,
        extra_payload={
            "source_type": _SUMMARY_SOURCE,
            "project_name": profile.project_name,
        },
    )
    return profile


def architecture_filter(layer: str | None = None) -> dict:
    payload = {
        "source_type": _SUMMARY_SOURCE,
    }
    if layer and layer in _SUMMARY_KINDS:
        payload["summary_kind"] = layer
    return payload


def format_profile(profile: ProjectProfile) -> str:
    return (
        f"## {profile.project_name}\n"
        f"- Koleksiyon: `{profile.collection}`\n"
        f"- Path: `{profile.project_path}`\n"
        f"- Diller: {', '.join(profile.languages) or '-'}\n"
        f"- Frameworkler: {', '.join(profile.frameworks) or '-'}\n"
        f"- Paket yöneticileri: {', '.join(profile.package_managers) or '-'}\n"
        f"- Modül kökleri: {', '.join(profile.module_roots[:8]) or '-'}\n"
        f"- Entrypoint'ler: {', '.join(profile.entrypoints) or '-'}\n"
        f"- Özet: {profile.summary}"
    )


def impact_report(
    profile: ProjectProfile,
    changed_paths: list[str],
    graph_hits: dict[str, list[str]],
) -> str:
    lines = [
        f"## Change Impact — {profile.project_name}",
        f"Toplam değişen yol: {len(changed_paths)}",
        "",
    ]
    for path in changed_paths:
        lines.append(f"### `{path}`")
        impacted = graph_hits.get(path, [])
        if impacted:
            for item in impacted[:12]:
                lines.append(f"- {item}")
        else:
            lines.append("- Graph üzerinde doğrudan ilişki bulunamadı.")
        lines.append("")
    return "\n".join(lines)
