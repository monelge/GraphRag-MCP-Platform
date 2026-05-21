from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from src.handlers.context import AppContext
from src.shared.config import config
from src.indexing.chunkers import secret_scanner
from src.indexing.pipelines.project_intelligence import sync_project_intelligence
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.ranking.answerability import Confidence, assess as assess_answerability
from src.retrieval.search.hybrid_search import (
    AGENT_DOC_FILTER,
    Filter as QFilter,
    FieldCondition as QFC,
    HybridSearcher,
    MatchValue as QMV,
)
from src.storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)
console = Console(stderr=True)


class IndexingHandler:
    """İndeksleme ve agent doc araçlarının uygulama katmanı."""

    INDEX_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".cs"}
    SUPPORTED_SOURCE_EXTENSIONS = {
        ".py",
        ".ts",
        ".tsx",
        ".cs",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".dart",
    }
    EXCLUDE_DIRS = {
        "node_modules",
        "bin",
        "obj",
        "dist",
        ".next",
        "__pycache__",
        ".venv",
        "venv",
        "migrations",
    }

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._ast = None
        self._md = None
        self._graph_extractor = None
        self._dense = None
        self._sparse = None

    def _get_ast(self):
        if self._ast is None:
            from src.indexing.chunkers.ast_chunker import ASTChunker

            self._ast = ASTChunker()
        return self._ast

    def _get_md(self):
        if self._md is None:
            from src.indexing.chunkers.markdown_chunker import MarkdownChunker

            self._md = MarkdownChunker()
        return self._md

    def _get_graph_extractor(self):
        if self._graph_extractor is None:
            from src.indexing.extractors.graph_extractor import GraphExtractor

            self._graph_extractor = GraphExtractor()
        return self._graph_extractor

    def _get_dense(self):
        if self._dense is None:
            from src.indexing.embedders.dense_embedder import DenseEmbedder

            self._dense = DenseEmbedder(redis_store=self.ctx.redis)
        return self._dense

    def _get_sparse(self):
        if self._sparse is None:
            from src.indexing.embedders.sparse_embedder import SparseEmbedder

            self._sparse = SparseEmbedder()
        return self._sparse

    @staticmethod
    def project_collection_name(project_path: str) -> str:
        return Path(project_path).resolve().name.replace(" ", "_")

    @staticmethod
    def normalize_changed_files(
        project_path: str,
        changed_files: list[str],
        extensions: set[str],
        exclude_dirs: set[str],
    ) -> tuple[list[str], list[str]]:
        """Değişen dosya yollarını proje köküne göre normalize eder."""
        project_root = Path(project_path).resolve()
        normalized: list[str] = []
        rejected: list[str] = []

        for raw in changed_files:
            raw = raw.strip()
            if not raw:
                continue

            candidate = Path(raw)
            options: list[Path] = []
            if candidate.is_absolute():
                options.append(candidate)
                try:
                    if project_root.name in candidate.parts:
                        project_idx = candidate.parts.index(project_root.name)
                        suffix_parts = candidate.parts[project_idx + 1 :]
                        options.append(project_root.joinpath(*suffix_parts))
                except ValueError:
                    pass
            else:
                options.append(project_root / candidate)

            resolved = next((path for path in options if path.exists()), None)
            if resolved is None:
                rejected.append(raw)
                continue

            if resolved.suffix not in extensions or exclude_dirs.intersection(resolved.parts):
                continue
            normalized.append(str(resolved))

        return list(dict.fromkeys(normalized)), rejected

    async def sync_project_foundation(self, project_path: str, collection: str) -> None:
        """Proje profili ve repo summary katmanını best-effort günceller."""
        try:
            profile = await sync_project_intelligence(
                project_path,
                collection=collection,
                redis_store=self.ctx.redis,
                neo4j_store=self.ctx.neo4j,
            )
            self.ctx.registry.upsert(profile)
        except Exception as exc:
            logger.warning("Project foundation sync başarısız: %s", exc)

    async def index_project(self, project_path: str, collection: str = "", batch_size: int = 32) -> str:
        """Kaynak kodu AST, graph ve vektör katmanlarına indeksler."""
        path_obj = Path(project_path).resolve()
        if not path_obj.exists():
            return f"❌ Proje yolu bulunamadı: {project_path}. (Container içinde /projects/ altında olduğundan emin olun)"
        if not path_obj.is_dir():
            return f"❌ Belirtilen yol bir dizin değil: {project_path}"

        if not collection:
            collection = self.project_collection_name(project_path)

        store = QdrantStore(collection=collection)
        await store.ensure_collection()
        already_indexed = await store.get_indexed_file_paths()
        files = [
            str(path)
            for path in path_obj.rglob("*")
            if path.suffix in self.INDEX_SOURCE_EXTENSIONS
            and ".git" not in path.parts
            and not self.EXCLUDE_DIRS.intersection(path.parts)
        ]
        
        if not files:
            return f"⚠️ İndekslenecek kaynak dosyası bulunamadı (.py, .ts, .tsx, .cs). Yol: {project_path}"

        remaining_files = [file_path for file_path in files if file_path not in already_indexed]

        if not remaining_files:
            await self.sync_project_foundation(project_path, collection)
            console.print(
                Panel(
                    f"[bold green]✓ Tüm dosyalar zaten indekslenmiş[/]\n"
                    f"[dim]{len(files)} dosya · koleksiyon: {collection}[/]",
                    border_style="green",
                )
            )
            return f"✅ Tüm dosyalar zaten indekslenmiş. ({len(files)} dosya, koleksiyon: '{collection}')"

        console.print(
            Panel(
                f"[bold cyan]🗂  {collection}[/]\n"
                f"[dim]Toplam: {len(files)} dosya  •  "
                f"{'Kaldığı yerden devam: ' + str(len(remaining_files)) + ' dosya kaldı' if already_indexed else str(len(remaining_files)) + ' dosya işlenecek'}[/]",
                border_style="cyan",
                title="[bold]GraphMCP İndeksleme[/]",
            )
        )

        indexed_count = 0
        total_chunks_processed = 0
        
        # Dosyaları gruplar halinde işle (Bellek ve performans optimizasyonu)
        file_batch_size = 50
        for i in range(0, len(remaining_files), file_batch_size):
            file_batch = remaining_files[i : i + file_batch_size]
            batch_chunks = []
            
            # 1. AST Parçalama
            for file_path in file_batch:
                try:
                    batch_chunks.extend(self._get_ast().chunk_file(file_path))
                except Exception as exc:
                    logger.error("Dosya parçalanamadı (%s): %s", file_path, exc)
            
            if not batch_chunks:
                continue

            # 2. Graph İlişkileri (Neo4j)
            try:
                relations = self._get_graph_extractor().extract_relationships(batch_chunks)
                await self.ctx.neo4j.upsert_nodes_and_relationships(relations, collection=collection)
            except Exception as exc:
                logger.error("Graph ilişkileri işlenemedi (batch %s): %s", i // file_batch_size, exc)

            # 3. Embedding ve Vektör Kayıt (Qdrant)
            # Alt batch'lere böl (Embedding model limitleri için)
            for j in range(0, len(batch_chunks), batch_size):
                chunk_batch = batch_chunks[j : j + batch_size]
                safe_batch = []
                for chunk in chunk_batch:
                    scan = secret_scanner.scan(chunk.code)
                    if not scan.should_skip:
                        chunk.code = scan.redacted_text
                        safe_batch.append(chunk)
                
                if not safe_batch:
                    continue

                try:
                    texts = [
                        f"# {c.name}\n# Tür: {c.chunk_type} | Dosya: {c.file_path}\n{c.code}"
                        for c in safe_batch
                    ]
                    dense_vecs = await self._get_dense().embed_batch(texts)
                    sparse_vecs = list(self._get_sparse().embed_batch(texts))
                    await store.upsert_chunks(safe_batch, dense_vecs, sparse_vecs)
                    indexed_count += len(safe_batch)
                except Exception as exc:
                    logger.error("Embedding/Qdrant hatası (batch %s): %s", i // file_batch_size, exc)
            
            total_chunks_processed += len(batch_chunks)
            logger.info("Batch tamamlandı: %s/%s dosya", i + len(file_batch), len(remaining_files))

        if total_chunks_processed == 0:
            return "⚠️ İndekslenecek kaynak dosyası bulunamadı veya işlenemedi."

        # Knowledge Plane V2: Final Analizler
        try:
            with console.status("[bold magenta]Mimari analizler (PageRank & Repo Map) güncelleniyor..."):
                await self.ctx.neo4j.run_pagerank_analysis(collection)
                await self.sync_project_foundation(project_path, collection)
        except Exception as exc:
            logger.warning("Mimari analiz güncellenemedi: %s", exc)

        console.print(
            Panel(
                f"[bold green]✓ İndeksleme tamamlandı[/]\n"
                f"[dim]{indexed_count} kod bloğu  •  Graph & Vektör hazır  •  koleksiyon: {collection}[/]",
                border_style="green",
            )
        )
        return f"✅ {indexed_count} kod bloğu ve Graph ilişkileri '{collection}' koleksiyonuna indekslendi."

    async def incremental_index_project(
        self,
        project_path: str,
        changed_files: list[str] | None = None,
        batch_size: int = 32,
    ) -> str:
        """Sadece değişen dosyaları yeniden indeksler."""
        rejected_files: list[str] = []
        if changed_files is None:
            if shutil.which("git") is None:
                return (
                    "⚠️ Container içinde 'git' binary'si yok ve changed_files verilmedi. "
                    "Artımlı indeksleme için hook'tan dosya listesini geçin veya image'a git ekleyin."
                )
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except FileNotFoundError:
                return (
                    "⚠️ Container içinde 'git' binary'si bulunamadı. "
                    "Artımlı indeksleme için changed_files parametresi kullanın."
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                reason = stderr or "git diff başarısız oldu"
                return (
                    f"⚠️ Git diff ile değişen dosyalar alınamadı: {reason}. "
                    "Repo erişimini kontrol edin veya changed_files parametresi kullanın."
                )

            changed_files, rejected_files = self.normalize_changed_files(
                project_path,
                result.stdout.splitlines(),
                self.INDEX_SOURCE_EXTENSIONS,
                self.EXCLUDE_DIRS,
            )
        else:
            changed_files, rejected_files = self.normalize_changed_files(
                project_path,
                changed_files,
                self.INDEX_SOURCE_EXTENSIONS,
                self.EXCLUDE_DIRS,
            )

        if not changed_files:
            if rejected_files:
                preview = ", ".join(rejected_files[:3])
                extra = " ..." if len(rejected_files) > 3 else ""
                return (
                    "⚠️ Değişen dosya listesi geldi ama proje içinde eşleşen desteklenen dosya bulunamadı. "
                    f"İlk eşleşmeyenler: {preview}{extra}"
                )
            return "✅ Desteklenen uzantılarda değişen dosya bulunamadı. İndeks güncel."

        collection = self.project_collection_name(project_path)
        if not await self.ctx.redis.acquire_lock(collection, op="incremental"):
            return f"⏳ '{collection}' için başka bir index işlemi devam ediyor. Lütfen bekleyin."

        try:
            store = QdrantStore(collection=collection)
            await store.ensure_collection()
            all_chunks = []
            for file_path in changed_files:
                all_chunks.extend(self._get_ast().chunk_file(file_path))

            if not all_chunks:
                return "⚠️ Değişen dosyalarda indekslenecek blok bulunamadı."

            relations = self._get_graph_extractor().extract_relationships(all_chunks)
            await self.ctx.neo4j.upsert_nodes_and_relationships(relations, collection=collection)

            indexed = 0
            for index in range(0, len(all_chunks), batch_size):
                batch = all_chunks[index : index + batch_size]
                safe_batch = []
                for chunk in batch:
                    scan = secret_scanner.scan(chunk.code)
                    if scan.should_skip:
                        continue
                    chunk.code = scan.redacted_text
                    safe_batch.append(chunk)

                if not safe_batch:
                    continue

                texts = [
                    f"# {chunk.name}\n# Tür: {chunk.chunk_type} | Dosya: {chunk.file_path}\n{chunk.code}"
                    for chunk in safe_batch
                ]
                dense_vecs = await self._get_dense().embed_batch(texts)
                sparse_vecs = list(self._get_sparse().embed_batch(texts))
                await store.upsert_chunks(safe_batch, dense_vecs, sparse_vecs)
                indexed += len(safe_batch)

            invalidated = await self.ctx.redis.invalidate_retrieval(collection)
            cache_note = f", {invalidated} ret cache key temizlendi" if invalidated else ""
            message = (
                f"✅ {len(changed_files)} değişen dosyadan {indexed} blok güncellendi "
                f"('{collection}' koleksiyonu{cache_note})."
            )
            if rejected_files:
                message += f" {len(rejected_files)} dosya yolunun proje içinde karşılığı bulunamadı ve atlandı."
            await self.sync_project_foundation(project_path, collection)
            return message
        finally:
            await self.ctx.redis.release_lock(collection, op="incremental")

    async def index_agent_docs(self, project_path: str) -> str:
        """.agent markdown belgelerini artımlı olarak indeksler."""
        project = Path(project_path).resolve()
        agent_dir = project / ".agent"
        if not agent_dir.exists():
            return f"⚠️ .agent/ dizini bulunamadı: {agent_dir}"

        collection = self.project_collection_name(project_path)
        if not await self.ctx.redis.acquire_lock(collection, op="agent_docs"):
            return f"⏳ '{collection}' için başka bir agent doc index işlemi devam ediyor."

        try:
            store = QdrantStore(collection=collection)
            await store.ensure_collection()
            exclude_patterns = {".env", "secrets.json", "user-secrets.json"}
            md_files = [path for path in agent_dir.rglob("*.md") if path.name not in exclude_patterns]
            if not md_files:
                return "⚠️ .agent/ dizininde .md dosyası bulunamadı."

            disk_paths: set[str] = set()
            new_chunks_count = 0
            updated_chunks_count = 0
            unchanged_count = 0
            files_processed = 0

            console.print(
                f"[bold cyan]📚 {collection} — Agent Doc İndeksleme[/]\n"
                f"[dim]{len(md_files)} dosya taranıyor...[/]"
            )

            for md_file in md_files:
                relative_path = str(md_file.relative_to(project))
                disk_paths.add(relative_path)
                existing = await store.get_agent_doc_chunks_by_path(relative_path)
                existing_by_chunk_id = {entry["chunk_id"]: entry for entry in existing}
                new_chunks = self._get_md().chunk_file(str(md_file), relative_path=relative_path)
                if not new_chunks:
                    files_processed += 1
                    continue

                to_upsert = []
                new_chunk_ids: set[str] = set()
                for chunk in new_chunks:
                    new_chunk_ids.add(chunk.chunk_id)
                    existing_entry = existing_by_chunk_id.get(chunk.chunk_id)
                    if existing_entry and existing_entry["checksum"] == chunk.checksum:
                        unchanged_count += 1
                    else:
                        to_upsert.append(chunk)

                if to_upsert:
                    texts = [f"{chunk.h1}\n{chunk.h2}\n{chunk.h3}\n{chunk.content[:1200]}" for chunk in to_upsert]
                    dense_vecs = await self._get_dense().embed_batch(texts)
                    sparse_vecs = list(self._get_sparse().embed_batch(texts))
                    await store.upsert_agent_doc_chunks(to_upsert, dense_vecs, sparse_vecs)
                    new_chunks_count += len(to_upsert)

                obsolete_point_ids = [
                    entry["point_id"]
                    for chunk_id, entry in existing_by_chunk_id.items()
                    if chunk_id not in new_chunk_ids
                ]
                if obsolete_point_ids:
                    await store.delete_chunks_by_point_ids(obsolete_point_ids)
                    updated_chunks_count += len(obsolete_point_ids)
                files_processed += 1

            indexed_paths = await store.get_all_agent_doc_paths()
            deleted_paths = indexed_paths - disk_paths
            for deleted_path in deleted_paths:
                await store.tombstone_chunks_by_path(deleted_path)

            invalidated = await self.ctx.redis.invalidate_retrieval(collection)
            cache_note = f", {invalidated} ret cache key temizlendi" if invalidated else ""
            summary = (
                f"✅ Agent doc indeksleme tamamlandı — '{collection}'\n"
                f"  {files_processed} dosya işlendi\n"
                f"  {new_chunks_count} chunk yüklendi / güncellendi\n"
                f"  {unchanged_count} chunk değişmemiş (atlandı)\n"
                f"  {updated_chunks_count} eski chunk temizlendi\n"
                f"  {len(deleted_paths)} silinmiş dosya tombstone edildi{cache_note}"
            )
            await self.sync_project_foundation(project_path, collection)
            console.print(f"[green]{summary}[/]")
            return summary
        finally:
            await self.ctx.redis.release_lock(collection, op="agent_docs")

    async def search_agent_docs(
        self,
        query: str,
        collection: str = "",
        layer: str | None = None,
        doc_priority: str | None = None,
    ) -> str:
        """Sadece agent_doc chunk'larında hibrit arama yapar."""
        collection = collection or config.default_collection
        cache_key = f"{query}|layer={layer}|priority={doc_priority}"
        t0 = time.monotonic()
        cached = await self.ctx.redis.get_retrieval(collection, cache_key)
        if cached is not None:
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                top1_score=0.0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                hit_count=0,
                query_type="agent_doc:cache_hit",
            )
            return cached

        must_conditions = list(AGENT_DOC_FILTER.must)
        if layer:
            must_conditions.append(QFC(key="layer", match=QMV(value=layer)))
        if doc_priority:
            must_conditions.append(QFC(key="doc_priority", match=QMV(value=doc_priority)))

        active_filter = QFilter(must=must_conditions)
        searcher = HybridSearcher(collection=collection)
        results = await searcher.search(query, top_k=8, query_filter=active_filter)
        if not results:
            await self.ctx.postgres.log_retrieval(
                collection=collection,
                redacted_query=query[:80],
                top1_score=0.0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                hit_count=0,
                query_type="agent_doc",
                answerability_fail=True,
            )
            filter_info = ""
            if layer or doc_priority:
                filter_info = f" (filtre: layer={layer or '*'}, priority={doc_priority or '*'})"
            return f"🔍 Agent dokümanlarda '{query}' için sonuç bulunamadı.{filter_info}"

        assessment = assess_answerability(results)
        if assessment.confidence == Confidence.INSUFFICIENT:
            return f"⚠️ Retrieval yetersiz: {assessment.reason}"

        builder = ContextBuilder(token_budget=4000)
        results = builder.build(results)
        output_lines = [f"## '{query}' — Agent Doc Sonuçları ({len(results)} chunk)\n"]
        if assessment.confidence.value == "weak":
            output_lines.append(f"> ⚠️ {assessment.reason}\n")

        for result in results:
            content = result.get("content", "")
            h1 = result.get("h1", "")
            h2 = result.get("h2", "")
            h3 = result.get("h3", "")
            rel_path = result.get("relative_path", "")
            priority = result.get("doc_priority", "")
            layer_name = result.get("layer", "")
            scan = secret_scanner.scan(content)
            safe_content = scan.redacted_text
            heading = " > ".join(value for value in [h1, h2, h3] if value)
            output_lines.append(
                f"### 📄 `{rel_path}`"
                + (f" [{priority}|{layer_name}]" if priority or layer_name else "")
                + (f" — {heading}" if heading else "")
                + f" (skor: {result.get('score', 0):.3f})\n"
                f"```markdown\n{safe_content[:1000]}\n```\n"
            )

        result_text = "\n".join(output_lines)
        await self.ctx.redis.set_retrieval(collection, cache_key, result_text)
        latency_ms = (time.monotonic() - t0) * 1000
        await self.ctx.postgres.log_retrieval(
            collection=collection,
            redacted_query=query[:80],
            top1_score=assessment.top1_score,
            latency_ms=int(latency_ms),
            hit_count=len(results),
            query_type="agent_doc",
        )
        return result_text
