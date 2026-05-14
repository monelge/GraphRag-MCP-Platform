#!/usr/bin/env python3
"""
GraphMCP — Generic Proje Yeniden İndeksleme Scripti (Force / Sıfırdan)

Kullanım:
    docker exec -it graph-mcp python3 /app/scripts/reindex.py \
        --project Vendoris \
        --path /projects/Vendoris

⚠ UYARI: Bu script mevcut collection verisini kalıcı olarak siler.
          Çalıştırmadan önce koleksiyon adını manuel olarak onaylamanız gerekir.
          Kaldığı yerden devam etmek için: index.py kullan
"""

import asyncio
import sys
import time
from pathlib import Path

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
from rich.prompt import Confirm

from src.indexing.chunkers.ast_chunker import ASTChunker
from src.indexing.chunkers.markdown_chunker import MarkdownChunker
from src.indexing.extractors.graph_extractor import GraphExtractor
from src.indexing.chunkers import secret_scanner
from src.indexing.embedders.dense_embedder import DenseEmbedder
from src.indexing.embedders.sparse_embedder import SparseEmbedder
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
    return [
        str(p) for p in project_path.rglob("*")
        if p.suffix in CODE_EXTENSIONS
        and ".git" not in p.parts
        and not EXCLUDE_DIRS.intersection(p.parts)
    ]


def _collect_agent_docs(project_path: Path) -> list[Path]:
    agent_dir = project_path / ".agent"
    if not agent_dir.exists():
        return []
    EXCLUDE_NAMES = {".env", "secrets.json", "user-secrets.json"}
    return [f for f in agent_dir.rglob("*.md") if f.name not in EXCLUDE_NAMES]


async def wipe_collection(collection: str, neo4j: Neo4jStore) -> None:
    """
    Qdrant collection'ını siler + Neo4j'deki collection node'larını kaldırır.
    Neden ayrı ayrı? Her store bağımsız — Neo4j ve Qdrant transaction paylaşmaz.
    """
    # Qdrant: collection'ı sil (tüm vektörler gider)
    qdrant = QdrantStore(collection=collection)
    try:
        await qdrant.client.delete_collection(collection)
        console.print(f"[yellow]  ✓ Qdrant collection silindi: {collection}[/]")
    except Exception:
        console.print(f"[dim]  ℹ Qdrant collection bulunamadı (ilk kez çalışıyor olabilir)[/]")

    # Neo4j: collection'a ait tüm node'ları kaldır
    neo4j.collection = collection
    records = await neo4j.execute_query(
        "MATCH (n {collection: $col}) DETACH DELETE n RETURN count(n) as deleted",
        {"col": collection},
    )
    deleted = records[0]["deleted"] if records else 0
    console.print(f"[yellow]  ✓ Neo4j'den {deleted} node silindi: {collection}[/]")


import subprocess

def _get_git_info(project_path: Path) -> tuple[str, str]:
    """Git bilgilerini (commit hash ve branch) döner."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_path, stderr=subprocess.STDOUT
        ).decode().strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path, stderr=subprocess.STDOUT
        ).decode().strip()
        return commit, branch
    except Exception:
        return "unknown", "unknown"


async def index_all_code(
    project_path: Path,
    collection: str,
    redis: RedisStore,
    neo4j: Neo4jStore,
    batch_size: int = 32,
) -> dict:
    """Tüm kod dosyalarını sıfırdan indeksler (hiçbir şeyi atlamaz)."""
    chunker   = ASTChunker()
    extractor = GraphExtractor()
    dense     = DenseEmbedder(redis_store=redis)
    sparse    = SparseEmbedder()
    store     = QdrantStore(collection=collection)
    await store.ensure_collection()

    commit_sha, branch = _get_git_info(project_path)
    all_files = _collect_files(project_path)
    stats = {
        "total_files":     len(all_files),
        "chunks":          0,
        "secrets_skipped": 0,
    }

    if not all_files:
        console.print("[yellow]⚠ İndekslenecek kaynak dosyası bulunamadı.[/]")
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
        task = prog.add_task("chunk", total=len(all_files))
        for f in all_files:
            file_chunks = chunker.chunk_file(f)
            # Faz 2: Provenance verilerini ekle
            for c in file_chunks:
                c.project = collection
                c.commit_sha = commit_sha
                c.branch = branch
            all_chunks.extend(file_chunks)
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
                dv = await dense.embed_batch(texts)
                sv = list(sparse.embed_batch(texts))
                await store.upsert_chunks(safe_batch, dv, sv)
                indexed += len(safe_batch)

            prog.advance(task, len(batch))

    stats["chunks"]          = indexed
    stats["secrets_skipped"] = secrets_skipped
    return stats


async def index_all_agent_docs(
    project_path: Path,
    collection: str,
    redis: RedisStore,
) -> dict:
    """Tüm agent doc dosyalarını sıfırdan indeksler."""
    md_files = _collect_agent_docs(project_path)
    stats = {"files": 0, "chunks": 0}

    if not md_files:
        return stats

    chunker = MarkdownChunker()
    dense   = DenseEmbedder(redis_store=redis)
    sparse  = SparseEmbedder()
    store   = QdrantStore(collection=collection)
    await store.ensure_collection()

    total_upserted = 0
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
            chunks = chunker.chunk_file(str(md_file), relative_path=relative_path)
            if chunks:
                texts = [
                    f"{c.h1}\n{c.h2}\n{c.h3}\n{c.content[:1200]}"
                    for c in chunks
                ]
                dv = await dense.embed_batch(texts)
                sv = list(sparse.embed_batch(texts))
                await store.upsert_agent_doc_chunks(chunks, dv, sv)
                total_upserted += len(chunks)
            prog.advance(task)

    stats["files"]  = len(md_files)
    stats["chunks"] = total_upserted
    return stats


async def run(project_name: str, project_path: str, batch_size: int) -> None:
    path       = Path(project_path).resolve()
    collection = project_name.replace(" ", "_")
    start_time = time.monotonic()

    if not path.exists():
        console.print(f"[bold red]✗ Proje dizini bulunamadı: {path}[/]")
        sys.exit(1)

    # ── Zorunlu Onay (atlanamaz) ──────────────────────────────────────────────
    console.print(Panel(
        f"[bold red]⚠ UYARI — Sıfırdan Yeniden İndeksleme[/]\n\n"
        f"  Koleksiyon : [bold]{collection}[/]\n"
        f"  Proje yolu : [dim]{path}[/]\n\n"
        f"[yellow]Bu işlem:[/]\n"
        f"  • Qdrant'taki '{collection}' koleksiyonunu [bold red]tamamen siler[/]\n"
        f"  • Neo4j'deki '{collection}' node'larını [bold red]tamamen siler[/]\n"
        f"  • Tüm dosyaları sıfırdan indeksler\n\n"
        f"[bold]Onaylamak için koleksiyon adını tam olarak yazın:[/] [cyan]{collection}[/]\n"
        f"[dim]Kaldığı yerden devam etmek için index.py kullanın.[/]",
        border_style="red",
        title="[bold red]reindex.py — Kullanıcı Onayı Zorunlu[/]",
    ))

    # Koleksiyon adını birebir yazdırma zorunluluğu — --yes bayrağı ile atlanamaz.
    # Neden? Yanlışlıkla yanlış proje silinmesini önlemek için.
    typed = console.input(f"\n[bold yellow]Koleksiyon adını yazın[/] ([cyan]{collection}[/]): ").strip()
    if typed != collection:
        console.print(f"[bold red]✗ Eşleşmedi. Beklenen: '{collection}' — Girilen: '{typed}'. İptal edildi.[/]")
        sys.exit(1)

    console.print(f"[green]✓ Onaylandı. İndeksleme başlıyor...[/]\n")

    # ── Bağlantılar ──────────────────────────────────────────────────────────
    redis = RedisStore()
    neo4j = Neo4jStore()
    await neo4j.connect()
    await neo4j.create_constraints()

    try:
        # ── Temizlik ──────────────────────────────────────────────────────────
        console.print(Rule("[bold red]Mevcut Veriyi Temizleme[/]"))
        await wipe_collection(collection, neo4j)

        # ── Kod İndeksleme ────────────────────────────────────────────────────
        console.print(Rule("[bold]Kaynak Kod İndeksleme[/]"))
        code_stats = await index_all_code(path, collection, redis, neo4j, batch_size)

        # ── Agent Docs İndeksleme ─────────────────────────────────────────────
        agent_stats: dict = {"files": 0, "chunks": 0}
        agent_dir = path / ".agent"
        if agent_dir.exists():
            console.print(Rule("[bold]Agent Docs İndeksleme[/]"))
            agent_stats = await index_all_agent_docs(path, collection, redis)
        else:
            console.print(f"[dim]ℹ .agent/ dizini yok, atlanıyor.[/]")

        # ── Özet Tablosu ──────────────────────────────────────────────────────
        elapsed = time.monotonic() - start_time
        table = Table(title="Yeniden İndeksleme Özeti", border_style="green", show_header=True)
        table.add_column("Metrik", style="cyan")
        table.add_column("Değer", style="bold white", justify="right")

        table.add_row("Koleksiyon", collection)
        table.add_row("Toplam dosya", str(code_stats["total_files"]))
        table.add_row("Qdrant chunk", str(code_stats["chunks"]))
        table.add_row("Gizli veri (atlandı)", str(code_stats["secrets_skipped"]))
        if agent_stats["files"] > 0:
            table.add_row("Agent doc dosya", str(agent_stats["files"]))
            table.add_row("Agent doc chunk", str(agent_stats["chunks"]))
        table.add_row("Süre", f"{elapsed:.1f}s")

        console.print(table)
        console.print(Panel(
            f"[bold green]✓ Yeniden indeksleme tamamlandı  •  {collection}[/]",
            border_style="green",
        ))

    finally:
        await neo4j.close()
        await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GraphMCP Generic Proje Yeniden İndeksleyici (force/sıfırdan)"
    )
    parser.add_argument("--project", required=True, help="Koleksiyon adı (örn: Vendoris)")
    parser.add_argument("--path",    required=True, help="Proje dizini (örn: /projects/Vendoris)")
    parser.add_argument("--batch",   type=int, default=32, help="Embedding batch boyutu (varsayılan: 32)")
    args = parser.parse_args()

    asyncio.run(run(args.project, args.path, args.batch))


if __name__ == "__main__":
    main()
