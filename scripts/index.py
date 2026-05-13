#!/usr/bin/env python3
"""
GraphMCP — Generic Proje İndeksleme Scripti (Incremental)

Kullanım:
    docker exec graph-mcp python3 /app/scripts/index.py \
        --project Vendoris \
        --path /projects/Vendoris

Davranış:
    - Zaten indekslenmiş dosyaları atlar (kaldığı yerden devam)
    - Hem Qdrant (vektör) hem Neo4j (graph) indeksler
    - .agent/ dizini varsa agent docs da indekslenir
    - Sıfırdan başlamak için: reindex.py kullan
"""

import asyncio
import sys
import time
from pathlib import Path

# Container içinde /app dizinini Python path'e ekle
sys.path.insert(0, "/app")

import argparse
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, BarColumn,
    TextColumn, TimeElapsedColumn, MofNCompleteColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.rule import Rule

from src.chunker.ast_chunker import ASTChunker
from src.chunker.markdown_chunker import MarkdownChunker
from src.chunker.graph_extractor import GraphExtractor
from src.chunker import secret_scanner
from src.embedder.dense_embedder import DenseEmbedder
from src.embedder.sparse_embedder import SparseEmbedder
from src.storage.qdrant_store import QdrantStore
from src.storage.redis_store import RedisStore
from src.storage.neo4j_store import Neo4jStore

console = Console()

EXCLUDE_DIRS = {
    "node_modules", "bin", "obj", "dist", ".next",
    "__pycache__", ".venv", "venv", "migrations",
}
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".cs"}


def _collect_files(project_path: Path) -> list[str]:
    """Proje dizininden indekslenecek kaynak dosyalarını toplar."""
    return [
        str(p) for p in project_path.rglob("*")
        if p.suffix in CODE_EXTENSIONS
        and ".git" not in p.parts
        and not EXCLUDE_DIRS.intersection(p.parts)
    ]


def _collect_agent_docs(project_path: Path) -> list[Path]:
    """Proje .agent/ dizinindeki markdown dosyalarını toplar."""
    agent_dir = project_path / ".agent"
    if not agent_dir.exists():
        return []
    EXCLUDE_NAMES = {".env", "secrets.json", "user-secrets.json"}
    return [f for f in agent_dir.rglob("*.md") if f.name not in EXCLUDE_NAMES]


async def index_code(
    project_path: Path,
    collection: str,
    redis: RedisStore,
    neo4j: Neo4jStore,
    batch_size: int = 32,
) -> dict:
    """
    Kod dosyalarını AST ile parçalar, Neo4j + Qdrant'a yazar.
    Kaldığı yerden devam eder — zaten indeksli dosyalar atlanır.
    """
    chunker   = ASTChunker()
    extractor = GraphExtractor()
    dense     = DenseEmbedder(redis_store=redis)
    sparse    = SparseEmbedder()
    store     = QdrantStore(collection=collection)
    await store.ensure_collection()

    all_files        = _collect_files(project_path)
    already_indexed  = await store.get_indexed_file_paths()
    remaining_files  = [f for f in all_files if f not in already_indexed]

    stats = {
        "total_files":     len(all_files),
        "skipped_files":   len(all_files) - len(remaining_files),
        "processed_files": len(remaining_files),
        "chunks":          0,
        "neo4j_nodes":     0,
        "secrets_skipped": 0,
    }

    if not remaining_files:
        console.print("[bold green]✓ Tüm kod dosyaları zaten indekslenmiş, atlanıyor.[/]")
        return stats

    # ── Aşama 1: AST Parçalama ────────────────────────────────────────────────
    all_chunks = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan][1/3] AST Parçalama[/]"),
        MofNCompleteColumn(),
        BarColumn(bar_width=36),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("chunk", total=len(remaining_files))
        for f in remaining_files:
            all_chunks.extend(chunker.chunk_file(f))
            prog.advance(task)

    if not all_chunks:
        console.print("[yellow]⚠ Kod bloğu üretilemedi (barrel/boş dosyalar?).[/]")
        return stats

    # ── Aşama 2: Graph İlişkileri → Neo4j ────────────────────────────────────
    with console.status(
        f"[bold magenta][2/3] Graph ilişkileri Neo4j'ye yazılıyor... ({len(all_chunks)} chunk)[/]"
    ):
        relations = extractor.extract_relationships(all_chunks)
        neo4j.collection = collection
        await neo4j.upsert_nodes_and_relationships(relations)

    # ── Aşama 3: Embedding + Qdrant Upsert ───────────────────────────────────
    indexed = 0
    secrets_skipped = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green][3/3] Embedding + Qdrant[/]"),
        MofNCompleteColumn(),
        BarColumn(bar_width=36),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("embed", total=len(all_chunks))
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i : i + batch_size]
            safe_batch = []
            for c in batch:
                scan = secret_scanner.scan(c.code)
                if scan.should_skip:
                    secrets_skipped += 1
                    continue
                c.code = scan.redacted_text
                safe_batch.append(c)

            if safe_batch:
                texts = [
                    f"# {c.name}\n# Tür: {c.chunk_type} | Dosya: {c.file_path}\n{c.code}"
                    for c in safe_batch
                ]
                dense_vecs  = await dense.embed_batch(texts)
                sparse_vecs = list(sparse.embed_batch(texts))
                await store.upsert_chunks(safe_batch, dense_vecs, sparse_vecs)
                indexed += len(safe_batch)

            prog.advance(task, len(batch))

    stats["chunks"]          = indexed
    stats["secrets_skipped"] = secrets_skipped
    return stats


async def index_agent_docs(
    project_path: Path,
    collection: str,
    redis: RedisStore,
) -> dict:
    """
    .agent/ dizinindeki markdown dosyalarını Qdrant'a yazar.
    Incremental: checksum değişmemiş chunk'lar atlanır.
    """
    md_files = _collect_agent_docs(project_path)
    stats = {
        "files":     0,
        "upserted":  0,
        "unchanged": 0,
        "tombstoned": 0,
    }

    if not md_files:
        return stats

    chunker = MarkdownChunker()
    dense   = DenseEmbedder(redis_store=redis)
    sparse  = SparseEmbedder()
    store   = QdrantStore(collection=collection)
    await store.ensure_collection()

    disk_paths: set[str] = set()
    upserted   = 0
    unchanged  = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue][📚] Agent Docs[/]"),
        MofNCompleteColumn(),
        BarColumn(bar_width=36),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("agent_docs", total=len(md_files))
        for md_file in md_files:
            relative_path = str(md_file.relative_to(project_path))
            disk_paths.add(relative_path)

            existing         = await store.get_agent_doc_chunks_by_path(relative_path)
            existing_by_cid  = {e["chunk_id"]: e for e in existing}
            new_chunks       = chunker.chunk_file(str(md_file), relative_path=relative_path)

            to_upsert   = []
            new_cids    = set()
            for chunk in new_chunks:
                new_cids.add(chunk.chunk_id)
                entry = existing_by_cid.get(chunk.chunk_id)
                if entry and entry["checksum"] == chunk.checksum:
                    unchanged += 1
                else:
                    to_upsert.append(chunk)

            if to_upsert:
                texts = [
                    f"{c.h1}\n{c.h2}\n{c.h3}\n{c.content[:1200]}"
                    for c in to_upsert
                ]
                dv = await dense.embed_batch(texts)
                sv = list(sparse.embed_batch(texts))
                await store.upsert_agent_doc_chunks(to_upsert, dv, sv)
                upserted += len(to_upsert)

            # Eski chunk'ları temizle
            obsolete = [
                e["point_id"]
                for cid, e in existing_by_cid.items()
                if cid not in new_cids
            ]
            if obsolete:
                await store.delete_chunks_by_point_ids(obsolete)

            prog.advance(task)

    # Diskten silinen dosyalar → tombstone
    indexed_paths = await store.get_all_agent_doc_paths()
    deleted_paths = indexed_paths - disk_paths
    for dp in deleted_paths:
        await store.tombstone_chunks_by_path(dp)

    stats["files"]     = len(md_files)
    stats["upserted"]  = upserted
    stats["unchanged"] = unchanged
    stats["tombstoned"] = len(deleted_paths)
    return stats


async def run(project_name: str, project_path: str, batch_size: int) -> None:
    path       = Path(project_path).resolve()
    collection = project_name.replace(" ", "_")
    start_time = time.monotonic()

    if not path.exists():
        console.print(f"[bold red]✗ Proje dizini bulunamadı: {path}[/]")
        sys.exit(1)

    console.print(Panel(
        f"[bold cyan]🗂  {collection}[/]  ·  [dim]{path}[/]\n"
        f"[dim]Mod: Incremental (kaldığı yerden devam)[/]",
        title="[bold]GraphMCP İndeksleme[/]",
        border_style="cyan",
    ))

    # ── Bağlantılar ──────────────────────────────────────────────────────────
    redis = RedisStore()
    neo4j = Neo4jStore()
    await neo4j.connect()
    await neo4j.create_constraints()

    try:
        # ── Kod İndeksleme ────────────────────────────────────────────────────
        console.print(Rule("[bold]Kaynak Kod İndeksleme[/]"))
        code_stats = await index_code(path, collection, redis, neo4j, batch_size)

        # ── Agent Docs İndeksleme ─────────────────────────────────────────────
        agent_stats: dict = {"files": 0, "upserted": 0, "unchanged": 0, "tombstoned": 0}
        agent_dir = path / ".agent"
        if agent_dir.exists():
            console.print(Rule("[bold]Agent Docs İndeksleme[/]"))
            agent_stats = await index_agent_docs(path, collection, redis)
        else:
            console.print(f"[dim]ℹ .agent/ dizini yok, atlanıyor.[/]")

        # ── Özet Tablosu ──────────────────────────────────────────────────────
        elapsed = time.monotonic() - start_time
        table = Table(title="İndeksleme Özeti", border_style="green", show_header=True)
        table.add_column("Metrik", style="cyan")
        table.add_column("Değer", style="bold white", justify="right")

        table.add_row("Koleksiyon", collection)
        table.add_row("Toplam dosya", str(code_stats["total_files"]))
        table.add_row("Atlanan (zaten indeksli)", str(code_stats["skipped_files"]))
        table.add_row("İşlenen dosya", str(code_stats["processed_files"]))
        table.add_row("Qdrant chunk", str(code_stats["chunks"]))
        table.add_row("Gizli veri (atlandı)", str(code_stats["secrets_skipped"]))
        if agent_stats["files"] > 0:
            table.add_row("Agent doc dosya", str(agent_stats["files"]))
            table.add_row("Agent chunk upsert", str(agent_stats["upserted"]))
            table.add_row("Agent chunk değişmemiş", str(agent_stats["unchanged"]))
        table.add_row("Süre", f"{elapsed:.1f}s")

        console.print(table)
        console.print(Panel(
            f"[bold green]✓ İndeksleme tamamlandı  •  {collection}[/]",
            border_style="green",
        ))

    finally:
        await neo4j.close()
        await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GraphMCP Generic Proje İndeksleyici (incremental)"
    )
    parser.add_argument("--project", required=True, help="Koleksiyon adı (örn: Vendoris)")
    parser.add_argument("--path",    required=True, help="Proje dizini (örn: /projects/Vendoris)")
    parser.add_argument("--batch",   type=int, default=32, help="Embedding batch boyutu (varsayılan: 32)")
    args = parser.parse_args()

    asyncio.run(run(args.project, args.path, args.batch))


if __name__ == "__main__":
    main()
