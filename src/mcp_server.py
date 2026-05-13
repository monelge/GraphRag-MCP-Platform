import asyncio
import logging
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import AsyncOpenAI
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn
from rich.panel import Panel
from rich import print as rprint

# httpx / openai HTTP istek loglarını sustur — konsolu kirletmesin
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

load_dotenv()

console = Console(stderr=True)  # MCP stdio'yu bozmamak için stderr kullan

from src.indexing.chunkers.ast_chunker import ASTChunker
from src.indexing.chunkers.markdown_chunker import MarkdownChunker
from src.indexing.extractors.graph_extractor import GraphExtractor
from src.indexing.chunkers import secret_scanner
from src.indexing.embedders.dense_embedder import DenseEmbedder
from src.indexing.embedders.sparse_embedder import SparseEmbedder
from src.storage.qdrant_store import QdrantStore
from src.storage.redis_store import RedisStore
from src.storage.postgres_store import PostgresStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.episodic_store import EpisodicStore, MemoryEntry, MemoryType
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep, TaskCheckpoint
from src.agent.tasks.task_store import TaskStore
from src.agent.orchestrator.state_machine import TaskOrchestrator
from src.execution.runners.command_runner import CommandRunner
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager
from src.control.models.gateway import ModelGateway
from src.control.evals.dataset_manager import DatasetManager, EvalCase
from src.control.evals.runner import EvalRunner
from src.indexing.pipelines.project_intelligence import (
    build_project_profile,
    format_profile,
    impact_report,
    sync_project_intelligence,
)
from src.shared.project_registry import ProjectRegistry
from src.retrieval.search.hybrid_search import (
    HybridSearcher, CODE_ONLY_FILTER, AGENT_DOC_FILTER,
    Filter as QFilter, FieldCondition as QFC, MatchValue as QMV,
)
from src.retrieval.search.query_classifier import classify as classify_query, TOP_K_BY_TYPE, should_rewrite
from src.retrieval.context.context_builder import ContextBuilder, compute_final_score
from src.retrieval.ranking.answerability import assess as assess_answerability, Confidence
from src.retrieval.ranking.reranker import LocalReranker
from src.retrieval.ranking.deduplicator import SemanticDeduplicator
from src.retrieval.context.token_budget import TokenBudgetOptimizer, get_budget_chars
from src.retrieval.search.graph_expansion import GraphExpander
from src.retrieval.search.impact_analysis import ImpactAnalyzer
from src.control.models.model_router import get_model
from src.retrieval.search.hyde import expand_query as hyde_expand, hyde_retrieve
from src.retrieval.context.compressor import compress_all as compress_chunks
from src.control.models.guardrail import RequestBudget, GuardrailError, fail_fast_token
from src.control.observability.tracer import PipelineTracer

# ── Singleton servis örnekleri ─────────────────────────────────────────────
_redis: RedisStore = RedisStore()
_postgres: PostgresStore = PostgresStore()
_neo4j: Neo4jStore = Neo4jStore()
_episodic: EpisodicStore = EpisodicStore()
_registry = ProjectRegistry()
_impact_analyzer = ImpactAnalyzer(_neo4j)
_task_store = TaskStore(_postgres)
_orchestrator = TaskOrchestrator(_task_store)
_command_runner = CommandRunner()
_runtime_manager = SandboxRuntimeManager(_command_runner)
_model_gateway = ModelGateway()
_dataset_manager = DatasetManager()
# Pipeline singleton'ları — durumsuz, paylaşımlı kullanım güvenli
_reranker    = LocalReranker()
_deduplicator = SemanticDeduplicator()
_budget_opt  = TokenBudgetOptimizer()
SUPPORTED_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".cs", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".swift", ".dart"}
EXCLUDE_DIRS = {"node_modules", "bin", "obj", "dist", ".next", "__pycache__", ".venv", "venv", "migrations"}


@asynccontextmanager
async def _lifespan(server):
    """MCP sunucusu yaşam döngüsü — bağlantıları aç/kapat."""
    await _postgres.connect()
    await _neo4j.connect()
    await _neo4j.create_constraints()
    yield
    await _redis.close()
    await _postgres.close()
    await _neo4j.close()


app = FastMCP("graph-mcp", lifespan=_lifespan)

# LLM istemcisi — query rewriting ve explain_code için paylaşımlı kullanılır.
# Neden modüler? Her araç kendi client oluşturmak yerine bu fabrika fonksiyonunu çağırır.
def _llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/GraphMCP",
            "X-Title": "GraphMCP",
        },
    )


def _project_collection_name(project_path: str) -> str:
    return Path(project_path).resolve().name.replace(" ", "_")


async def _sync_project_foundation(project_path: str, collection: str) -> None:
    """
    V2 foundation: proje profili + repo summary katmanını güncel tut.
    Hata olması indexing'i durdurmamalı.
    """
    try:
        profile = await sync_project_intelligence(
            project_path, 
            collection=collection, 
            redis_store=_redis,
            neo4j_store=_neo4j
        )
        _registry.upsert(profile)
    except Exception as exc:
        logging.getLogger(__name__).warning("Project foundation sync başarısız: %s", exc)


def _normalize_changed_files(
    project_path: str,
    changed_files: list[str],
    extensions: set[str],
    exclude_dirs: set[str],
) -> tuple[list[str], list[str]]:
    """
    Gelen değişen dosya listesinde relative, absolute veya farklı mount'tan gelen
    host path'lerini proje köküne göre normalize eder.
    """
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

        resolved = next((p for p in options if p.exists()), None)
        if resolved is None:
            rejected.append(raw)
            continue

        if (
            resolved.suffix not in extensions
            or exclude_dirs.intersection(resolved.parts)
        ):
            continue

        normalized.append(str(resolved))

    # Aynı dosya birden fazla path formatıyla gelirse tekilleştir
    return list(dict.fromkeys(normalized)), rejected


# --- ARAÇ 1: Projeyi İndeksle (tam indeksleme) ---
@app.tool()
async def index_project(project_path: str, collection: str = "", batch_size: int = 32) -> str:
    """
    Verilen dizindeki tüm kaynak dosyaları AST ile parçalar,
    vektörlere (Qdrant) ve ilişkilere (Neo4j) çevirerek kaydeder.
    collection: boş bırakılırsa proje klasör adı kullanılır.
    """
    chunker = ASTChunker()
    extractor = GraphExtractor()
    dense   = DenseEmbedder(redis_store=_redis)
    sparse  = SparseEmbedder()
    
    # Collection ismi verilmediyse proje klasör adını al
    if not collection:
        collection = Path(project_path).resolve().name.replace(" ", "_")
    
    store = QdrantStore(collection=collection)
    await store.ensure_collection()

    # Daha önce indekslenmiş dosyaları Qdrant'tan çek — kaldığı yerden devam eder.
    already_indexed = await store.get_indexed_file_paths()

    extensions = {".py", ".ts", ".tsx", ".cs"}
    # node_modules, bin, obj gibi üretilmiş/bağımlılık klasörlerini hariç tut
    files = [
        str(p) for p in Path(project_path).rglob("*")
        if p.suffix in extensions
        and ".git" not in p.parts
        and not EXCLUDE_DIRS.intersection(p.parts)
    ]

    remaining_files = [f for f in files if f not in already_indexed]

    if not remaining_files:
        await _sync_project_foundation(project_path, collection)
        console.print(Panel(
            f"[bold green]✓ Tüm dosyalar zaten indekslenmiş[/]\n"
            f"[dim]{len(files)} dosya · koleksiyon: {collection}[/]",
            border_style="green"
        ))
        return f"✅ Tüm dosyalar zaten indekslenmiş. ({len(files)} dosya, koleksiyon: '{collection}')"

    console.print(Panel(
        f"[bold cyan]🗂  {collection}[/]\n"
        f"[dim]Toplam: {len(files)} dosya  •  "
        f"{'Kaldığı yerden devam: ' + str(len(remaining_files)) + ' dosya kaldı' if already_indexed else str(len(remaining_files)) + ' dosya işlenecek'}[/]",
        border_style="cyan", title="[bold]GraphMCP İndeksleme[/]"
    ))

    # 1. AST ile chunk'lara böl
    all_chunks = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]AST parçalama[/]"),
        MofNCompleteColumn(),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("chunking", total=len(remaining_files))
        for f in remaining_files:
            all_chunks.extend(chunker.chunk_file(f))
            progress.advance(task)

    if not all_chunks:
        console.print("[yellow]⚠ İndekslenecek kod bloğu bulunamadı.[/]")
        return "⚠️ İndekslenecek kaynak dosyası bulunamadı."

    # 2. Graph İlişkilerini Çıkar ve Neo4j'ye Kaydet
    with console.status("[bold magenta]Graph ilişkileri Neo4j'ye işleniyor..."):
        relations = extractor.extract_relationships(all_chunks)
        # collection bilgisini Neo4j store'a set et — proje izolasyonu için
        _neo4j.collection = collection
        await _neo4j.upsert_nodes_and_relationships(relations)

    # 3. Embed + Qdrant upsert (Vektör İndeksleme)
    indexed = 0
    total_chunks = len(all_chunks)
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]Embedding + Qdrant Kayıt[/]"),
        MofNCompleteColumn(),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("embedding", total=total_chunks)
        for i in range(0, total_chunks, batch_size):
            batch = all_chunks[i : i + batch_size]
            safe_batch = []
            for c in batch:
                scan = secret_scanner.scan(c.code)
                if scan.should_skip:
                    continue
                c.code = scan.redacted_text
                safe_batch.append(c)

            if not safe_batch:
                progress.advance(task, len(batch))
                continue

            texts = [
                f"# {c.name}\n# Tür: {c.chunk_type} | Dosya: {c.file_path}\n{c.code}"
                for c in safe_batch
            ]
            dense_vecs  = await dense.embed_batch(texts)
            sparse_vecs = list(sparse.embed_batch(texts))
            await store.upsert_chunks(safe_batch, dense_vecs, sparse_vecs)
            indexed += len(safe_batch)
            progress.advance(task, len(batch))

    console.print(Panel(
        f"[bold green]✓ İndeksleme tamamlandı[/]\n"
        f"[dim]{indexed} chunk  •  Graph & Vektör hazır  •  koleksiyon: {collection}[/]",
        border_style="green"
    ))
    await _sync_project_foundation(project_path, collection)
    return f"✅ {indexed} kod bloğu ve Graph ilişkileri '{collection}' koleksiyonuna indekslendi."


# --- ARAÇ 2: Artımlı İndeksle (sadece değişen dosyalar) ---
@app.tool()
async def incremental_index_project(
    project_path: str,
    changed_files: list[str] | None = None,
    batch_size: int = 32,
) -> str:
    """
    Değişen dosyaları tespit eder ve onları yeniden indeksler.

    changed_files parametresi verilirse (post-commit hook'tan geçirilir) doğrudan o
    dosyaları işler — Docker içinde git binary'sine gerek kalmaz.
    Verilmezse container içinden git diff ile tespit etmeye çalışır.
    """
    extensions = {".py", ".ts", ".tsx", ".cs"}
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

        changed_files, rejected_files = _normalize_changed_files(
            project_path,
            result.stdout.splitlines(),
            extensions,
            EXCLUDE_DIRS,
        )
    else:
        changed_files, rejected_files = _normalize_changed_files(
            project_path,
            changed_files,
            extensions,
            EXCLUDE_DIRS,
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

    collection = _project_collection_name(project_path)

    # Eş zamanlı index işlemlerini engelle — duplikasyon veya tombstone çakışması önler
    if not await _redis.acquire_lock(collection, op="incremental"):
        return f"⏳ '{collection}' için başka bir index işlemi devam ediyor. Lütfen bekleyin."

    try:
        chunker = ASTChunker()
        dense   = DenseEmbedder(redis_store=_redis)
        sparse  = SparseEmbedder()
        store   = QdrantStore(collection=collection)

        await store.ensure_collection()

        all_chunks = []
        for f in changed_files:
            all_chunks.extend(chunker.chunk_file(f))

        if not all_chunks:
            return "⚠️ Değişen dosyalarda indekslenecek blok bulunamadı."

        # 1. Graph Güncelleme (Neo4j) — collection ile izole
        # Not: Eski ilişkileri temizleyip yenilerini ekler (upsert mantığı)
        extractor = GraphExtractor()
        relations = extractor.extract_relationships(all_chunks)
        _neo4j.collection = collection
        await _neo4j.upsert_nodes_and_relationships(relations)

        # 2. Vektör Güncelleme (Qdrant)
        indexed = 0
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i : i + batch_size]
            safe_batch = []
            for c in batch:
                scan = secret_scanner.scan(c.code)
                if scan.should_skip:
                    continue
                c.code = scan.redacted_text
                safe_batch.append(c)

            if not safe_batch:
                continue

            texts = [
                f"# {c.name}\n# Tür: {c.chunk_type} | Dosya: {c.file_path}\n{c.code}"
                for c in safe_batch
            ]
            dense_vecs  = await dense.embed_batch(texts)
            sparse_vecs = list(sparse.embed_batch(texts))
            await store.upsert_chunks(safe_batch, dense_vecs, sparse_vecs)
            indexed += len(safe_batch)

        # Index tamamlandı — stale retrieval cache'i temizle
        invalidated = await _redis.invalidate_retrieval(collection)
        cache_note = f", {invalidated} ret cache key temizlendi" if invalidated else ""

        message = (
            f"✅ {len(changed_files)} değişen dosyadan {indexed} blok güncellendi "
            f"('{collection}' koleksiyonu{cache_note})."
        )
        if rejected_files:
            message += f" {len(rejected_files)} dosya yolunun proje içinde karşılığı bulunamadı ve atlandı."
        await _sync_project_foundation(project_path, collection)
        return message
    finally:
        # Hata olsa bile lock serbest bırakılmalı
        await _redis.release_lock(collection, op="incremental")


# --- ARAÇ 3: Kod Ara ---
@app.tool()
async def search_code(
    query: str,
    collection: str = "",
    top_k: int = 0,
    rewrite_query: bool | None = None,
) -> str:
    """
    Doğal dil sorgusuyla hibrit kod araması — tam pipeline:
      QueryClassifier → ExactCache → SemanticCache
      → ConditionalRewrite/HyDE → HybridRetrieval(top20)
      → GraphAugment → LocalReranker → SemanticDedup
      → final_score → Answerability → TokenBudget
      → ContextCompressor → StructuredContextBuilder → Yanıt

    collection: boş bırakılırsa DEFAULT_COLLECTION env'den okunur.
    rewrite_query: None=otomatik (should_rewrite), True=zorla, False=hiçbir zaman.
    """
    collection = collection or os.getenv("DEFAULT_COLLECTION", "codebase")
    t0 = time.monotonic()
    budget = RequestBudget()
    tracer = PipelineTracer(query=query, collection=collection)

    # 1. QueryClassifier — query tip ve top_k belirle
    query_type = classify_query(query)
    if top_k == 0:
        top_k = TOP_K_BY_TYPE[query_type]

    # 2. Exact-match cache kontrolü
    cached = await _redis.get_retrieval(collection, query)
    if cached is not None:
        await _postgres.log_retrieval(
            collection=collection, redacted_query=query[:80],
            query_type=f"{query_type}:exact_cache", cache_hit=True,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return cached

    # 3. Semantic cache kontrolü (query embedding benzerliği)
    dense_embedder = DenseEmbedder(redis_store=_redis)
    query_emb = (await dense_embedder.embed_batch([query]))[0]

    similar_hash = await _redis.find_similar_cached_query(collection, query_emb)
    if similar_hash:
        semantic_key = f"__hash__:{similar_hash}"
        sem_cached = await _redis.get_retrieval(collection, semantic_key)
        if sem_cached:
            await _postgres.log_retrieval(
                collection=collection, redacted_query=query[:80],
                query_type=f"{query_type}:semantic_cache", cache_hit=True,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return sem_cached

    await _redis.set_query_embedding(collection, query, query_emb)

    # 4. Koşullu Query Rewrite / HyDE Expansion
    effective_query = query
    do_rewrite = rewrite_query if rewrite_query is not None else should_rewrite(query)
    expansions: list[str] = []

    if do_rewrite:
        try:
            budget.consume_aux_llm("query_rewrite_or_hyde")
            client = _llm_client()
            # HyDE: 3 expansion üret (rewrite yerine daha zengin sinyal)
            with tracer.step("hyde"):
                expansions = await hyde_expand(
                    query, llm_client=client, model=get_model("query_rewrite")
                )
                tracer.record("hyde", item_count=len(expansions))
            if expansions:
                effective_query = expansions[0]   # İlk expansion birincil sorgu
        except GuardrailError as ge:
            # AUX call limiti aşıldı → rewrite/HyDE atla
            pass
        except Exception:
            effective_query = query

    # 5. HybridRetrieval — HyDE varsa paralel, yoksa tek sorgu
    searcher = HybridSearcher(collection=collection)
    with tracer.step("retrieval") as t_ret:
        if expansions:
            candidates = await hyde_retrieve(
                query=query,
                expansions=expansions,
                searcher=searcher,
                query_filter=CODE_ONLY_FILTER,
                top_k=top_k,
            )
        else:
            candidates = await searcher.search(
                effective_query, top_k=top_k, fetch_k=top_k * 2, query_filter=CODE_ONLY_FILTER
            )
        tracer.record("retrieval", item_count=len(candidates))

    if not candidates:
        return "🔍 Sorguya uygun kod bloğu bulunamadı."

    # 6. Graph-First Candidate Augmentation (code_relation / broad_summary)
    expander = GraphExpander(_neo4j)
    with tracer.step("graph_augment"):
        candidates = await expander.augment_candidates(
            query=query, collection=collection,
            normal_candidates=candidates, query_type=query_type, top_k=top_k,
        )
        tracer.record("graph_augment", item_count=len(candidates))

    # 7. CrossEncoder Reranker
    t_rerank = time.monotonic()
    with tracer.step("rerank"):
        reranked = _reranker.rerank(query, candidates, top_n=min(top_k, 5))
        tracer.record("rerank", item_count=len(reranked))
    rerank_ms = int((time.monotonic() - t_rerank) * 1000)

    # 8. Semantic Deduplication
    with tracer.step("dedup"):
        deduped = _deduplicator.deduplicate(reranked)
        tracer.record("dedup", item_count=len(deduped))

    # 9. Graph centrality (enrich)
    with tracer.step("graph_expand"):
        entrypoints = [c.get("name", "") for c in deduped if c.get("name")]
        graph_nodes = await expander.expand(entrypoints)
        centrality = await expander.get_centrality(graph_nodes)
        for c in deduped:
            c["graph_centrality"] = centrality.get(c.get("name", ""), 0.0)
        tracer.record("graph_expand", item_count=len(graph_nodes))

    # 10. Answerability kontrolü — diversity-aware
    assessment = assess_answerability(deduped, query_type=query_type)
    if assessment.confidence == Confidence.INSUFFICIENT:
        trace_summary = tracer.finish()
        await _postgres.log_retrieval(
            collection=collection, redacted_query=query[:80],
            query_type=query_type, top1_score=assessment.top1_score,
            latency_ms=int((time.monotonic() - t0) * 1000),
            rerank_latency_ms=rerank_ms, answerability_fail=True,
        )
        return f"⚠️ Retrieval yetersiz: {assessment.reason}"

    # 11. Token Budget + ContextBuilder
    budget_chars = get_budget_chars(query_type)
    try:
        fail_fast_token(budget_chars // 4, context=f"search_code:{query_type}")
    except GuardrailError as ge:
        return f"⚠️ Token limiti: {ge}"

    builder = ContextBuilder(token_budget=budget_chars // 4, query_type=query_type)
    final_chunks = builder.build(deduped)

    # 12. Context Compressor (conservative)
    with tracer.step("compress"):
        final_chunks = compress_chunks(final_chunks)
        total_chars = sum(len(c.get("code") or c.get("content") or "") for c in final_chunks)
        tracer.record("compress", token_count=total_chars // 4)

    # 13. Çıktı formatla
    header = f"## '{query}' için Sonuçlar ({len(final_chunks)} blok)"
    if do_rewrite and expansions:
        header += f"\n> 🔍 HyDE expansion: _{', '.join(expansions[:2])}_"
    if assessment.confidence.value == "weak":
        header += f"\n> ⚠️ {assessment.reason}"

    output = [header + "\n"]
    for r in final_chunks:
        fs = r.get("final_score", r.get("score", 0.0))
        ratio = r.get("_compression_ratio")
        compress_note = f" 📦 {ratio:.0%}" if ratio and ratio < 1.0 else ""
        output.append(
            f"### `{r['name']}` ({r['type']}) — final_score: {fs:.3f}{compress_note}\n"
            f"📄 `{r['file']}` satır {r['lines']}\n"
            f"```{r['language']}\n{r['code'][:800]}\n```\n"
        )
    result_text = "\n".join(output)

    # 14. Cache'e yaz + Postgres log
    await _redis.set_retrieval(collection, query, result_text)
    latency_ms = int((time.monotonic() - t0) * 1000)
    await _postgres.log_retrieval(
        collection=collection, redacted_query=query[:80],
        query_type=query_type, top_k=top_k,
        hit_count=len(final_chunks), top1_score=assessment.top1_score,
        latency_ms=latency_ms, rerank_latency_ms=rerank_ms,
        token_usage=total_chars // 4, cache_hit=False,
        answerability_fail=assessment.is_failure,
    )
    return result_text

# --- ARAÇ 4: Kodu Açıkla (Structured Output) ---
@app.tool()
async def explain_code(
    query: str,
    collection: str = "",
    top_k: int = 5,
) -> str:
    """
    Hibrit arama + Rerank + LLM analizi → Structured JSON çıktı.

    Çıktı alanları:
      purpose, entrypoints, dependencies, flow_summary,
      security_risks, side_effects, related_components

    Model routing: architecture/broad = güçlü model, diğerleri = gpt-4o-mini.
    collection: boş bırakılırsa DEFAULT_COLLECTION env'den okunur.
    """
    import json as _json

    collection = collection or os.getenv("DEFAULT_COLLECTION", "codebase")
    query_type = classify_query(query)

    # 1. HybridRetrieval + Rerank + Dedup
    searcher  = HybridSearcher(collection=collection)
    candidates = await searcher.search(
        query, top_k=top_k * 2, fetch_k=top_k * 3, query_filter=CODE_ONLY_FILTER
    )

    if not candidates:
        return "🔍 Sorguya uygun kod bloğu bulunamadı."

    reranked  = _reranker.rerank(query, candidates, top_n=top_k)
    deduped   = _deduplicator.deduplicate(reranked)

    # 2. Graph Expansion — bağımlılık zincirini context'e ekle
    expander     = GraphExpander(_neo4j)
    entrypoints  = [c.get("name", "") for c in deduped if c.get("name")]
    graph_nodes  = await expander.expand(entrypoints)
    centrality   = await expander.get_centrality(graph_nodes)
    for c in deduped:
        c["graph_centrality"] = centrality.get(c.get("name", ""), 0.0)

    # 3. Answerability
    assessment = assess_answerability(deduped)
    if assessment.confidence == Confidence.INSUFFICIENT:
        return f"⚠️ Retrieval yetersiz: {assessment.reason}"

    # 4. ContextBuilder — model routing'e göre budget
    budget_chars = get_budget_chars(query_type)
    builder = ContextBuilder(token_budget=budget_chars // 4, query_type=query_type)
    final_chunks = builder.build(deduped)

    # 5. LLM — model routing (architecture → güçlü model)
    model_task = "architecture" if query_type == "broad_summary" else "explain"
    model = get_model(model_task)

    code_context = "\n\n".join([
        f"### {r['name']} ({r.get('type','')}) — {r['file']} satır {r['lines']}\n"
        f"```{r['language']}\n{r['code'][:700]}\n```"
        for r in final_chunks
    ])

    client = _llm_client()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": (
                "Sen uzman bir yazılım mimarısın. "
                "Verilen kod bloklarını analiz ederek YALNIZCA geçerli JSON döndür. "
                "Şema:\n"
                '{"purpose":"","entrypoints":[],"dependencies":[],'
                '"flow_summary":[],"security_risks":[],'
                '"side_effects":[],"related_components":[]}\n'
                "Tüm değerler Türkçe olsun. JSON dışında hiçbir şey yazma."
            )},
            {"role": "user", "content": f"Soru: {query}\n\nKod:\n{code_context}"},
        ],
        max_tokens=1800, temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()

    # JSON parse — hatalıysa düz metin olarak döndür
    try:
        parsed = _json.loads(raw)
        output_lines = [f"## 🔍 `{query}` — Kod Analizi\n"]
        if parsed.get("purpose"):
            output_lines.append(f"**Amaç:** {parsed['purpose']}\n")
        if parsed.get("entrypoints"):
            output_lines.append("**Giriş Noktaları:** " + ", ".join(f"`{e}`" for e in parsed["entrypoints"]))
        if parsed.get("dependencies"):
            output_lines.append("**Bağımlılıklar:** " + ", ".join(f"`{d}`" for d in parsed["dependencies"]))
        if parsed.get("flow_summary"):
            output_lines.append("\n**Akış:**")
            for step in parsed["flow_summary"]:
                output_lines.append(f"  {step}")
        if parsed.get("security_risks"):
            output_lines.append("\n**⚠️ Güvenlik Riskleri:**")
            for r in parsed["security_risks"]:
                output_lines.append(f"  - {r}")
        if parsed.get("side_effects"):
            output_lines.append("\n**Yan Etkiler:** " + "; ".join(parsed["side_effects"]))
        if parsed.get("related_components"):
            output_lines.append("**İlgili Bileşenler:** " + ", ".join(f"`{c}`" for c in parsed["related_components"]))

        if assessment.confidence.value == "weak":
            output_lines.append(f"\n> ⚠️ {assessment.reason}")

        output_lines.append("\n---\n## 📄 Kaynak Kod Blokları\n")
        for r in final_chunks:
            output_lines.append(
                f"### `{r['name']}` ({r['type']}) — {r['file']} satır {r['lines']}\n"
                f"```{r['language']}\n{r['code'][:800]}\n```\n"
            )
        return "\n".join(output_lines)
    except Exception:
        # JSON parse başarısız → ham LLM çıktısını döndür
        return f"## Kod Analizi: '{query}'\n\n{raw}"


# --- ARAÇ 5: Agent Dokümanlarını İndeksle ---
@app.tool()
async def index_agent_docs(project_path: str) -> str:
    """
    Proje .agent/ dizinindeki markdown dosyalarını chunk'larına böler ve Qdrant'a yükler.

    Özellikler:
      - Incremental sync: checksum değişmemiş chunk'lar atlanır (embed + upsert yok)
      - Best-effort two-phase sync: önce yeni chunk'lar yüklenir, ardından eskiler silinir
        (tam atomiklik yok; upsert başarılı ama delete başarısız → duplikasyon, retry ile düzelir)
      - Tombstone: diskten silinen dosyaların chunk'larına is_deleted=True yazılır
      - SecretScanner: risk_score > 0.8 olan chunk'lar index'e girmez
    """
    project = Path(project_path).resolve()
    agent_dir = project / ".agent"

    if not agent_dir.exists():
        return f"⚠️ .agent/ dizini bulunamadı: {agent_dir}"

    collection = project.name.replace(" ", "_")

    # Eş zamanlı agent doc index işlemlerini engelle
    if not await _redis.acquire_lock(collection, op="agent_docs"):
        return f"⏳ '{collection}' için başka bir agent doc index işlemi devam ediyor."

    try:
        chunker = MarkdownChunker()
        dense   = DenseEmbedder(redis_store=_redis)
        sparse  = SparseEmbedder()
        store   = QdrantStore(collection=collection)

        await store.ensure_collection()

        # Disk'teki .md dosyalarını tara (exclusion: .env, *.key, *.pem gibi — .agent/ altında
        # bunlar normalde bulunmaz ama yine de kontrol edilir)
        EXCLUDE_PATTERNS = {".env", "secrets.json", "user-secrets.json"}
        md_files = [
            f for f in agent_dir.rglob("*.md")
            if f.name not in EXCLUDE_PATTERNS
        ]

        if not md_files:
            return "⚠️ .agent/ dizininde .md dosyası bulunamadı."

        disk_paths: set[str] = set()
        new_chunks_count = 0
        updated_chunks_count = 0
        unchanged_count = 0
        files_processed = 0

        console.print(
            f"[bold cyan]📚 {collection} — Agent Doc İndeksleme[/]\n"
            f"[dim]{len(md_files)} dosya taranıyor...[/]",
        )

        for md_file in md_files:
            relative_path = str(md_file.relative_to(project))
            disk_paths.add(relative_path)

            # Mevcut Qdrant chunk'larını çek: {point_id, chunk_id, checksum}
            existing = await store.get_agent_doc_chunks_by_path(relative_path)
            existing_by_chunk_id: dict[str, dict] = {e["chunk_id"]: e for e in existing}

            # Yeni chunk'lar üret
            new_chunks = chunker.chunk_file(str(md_file), relative_path=relative_path)

            # SecretScanner skip istatistiği (chunker içinde de çalışır, burada sayıyoruz)
            # chunk_file dönüş listesi zaten taranmış — burada tekrar taramaya gerek yok.

            if not new_chunks:
                files_processed += 1
                continue

            # Incremental sync: checksum karşılaştır
            to_upsert: list = []
            new_chunk_ids: set[str] = set()

            for chunk in new_chunks:
                new_chunk_ids.add(chunk.chunk_id)
                existing_entry = existing_by_chunk_id.get(chunk.chunk_id)
                if existing_entry and existing_entry["checksum"] == chunk.checksum:
                    # Değişmemiş: atla
                    unchanged_count += 1
                else:
                    to_upsert.append(chunk)

            # Phase 1: Yeni ve değişmiş chunk'ları yükle
            if to_upsert:
                texts = [
                    f"{c.h1}\n{c.h2}\n{c.h3}\n{c.content[:1200]}"
                    for c in to_upsert
                ]
                dense_vecs  = await dense.embed_batch(texts)
                sparse_vecs = list(sparse.embed_batch(texts))
                await store.upsert_agent_doc_chunks(to_upsert, dense_vecs, sparse_vecs)
                new_chunks_count += len(to_upsert)

            # Phase 2: Artık olmayan eski chunk_id'lerin point_id'lerini sil
            obsolete_point_ids = [
                e["point_id"]
                for cid, e in existing_by_chunk_id.items()
                if cid not in new_chunk_ids
            ]
            if obsolete_point_ids:
                await store.delete_chunks_by_point_ids(obsolete_point_ids)
                updated_chunks_count += len(obsolete_point_ids)

            files_processed += 1

        # Diskten silinen dosyalar → tombstone
        indexed_paths = await store.get_all_agent_doc_paths()
        deleted_paths = indexed_paths - disk_paths

        for deleted_path in deleted_paths:
            await store.tombstone_chunks_by_path(deleted_path)

        # Index tamamlandı — stale retrieval cache'i temizle
        invalidated = await _redis.invalidate_retrieval(collection)
        cache_note = f", {invalidated} ret cache key temizlendi" if invalidated else ""

        summary = (
            f"✅ Agent doc indeksleme tamamlandı — '{collection}'\n"
            f"  {files_processed} dosya işlendi\n"
            f"  {new_chunks_count} chunk yüklendi / güncellendi\n"
            f"  {unchanged_count} chunk değişmemiş (atlandı)\n"
            f"  {len(deleted_paths)} silinmiş dosya tombstone edildi{cache_note}"
        )
        await _sync_project_foundation(project_path, collection)
        console.print(f"[green]{summary}[/]")
        return summary
    finally:
        # Hata olsa bile lock serbest bırakılmalı
        await _redis.release_lock(collection, op="agent_docs")


# --- ARAÇ 6: Agent Dokümanlarında Ara ---
@app.tool()
async def search_agent_docs(
    query: str,
    collection: str = "",
    layer: str | None = None,
    doc_priority: str | None = None,
) -> str:
    """
    Yalnızca source_type='agent_doc' chunk'larında hibrit arama yapar.

    layer filtresi: 'backend' | 'frontend' | 'security' | 'rules' | 'entity' | 'init' | 'state'
    doc_priority:   'critical' | 'high' | 'normal'

    Sonuçlara SecretScanner uygulanır (last-mile defense).
    collection boş bırakılırsa DEFAULT_COLLECTION env'den okunur.
    """
    collection = collection or os.getenv("DEFAULT_COLLECTION", "codebase")

    # Retrieval cache kontrolü (layer/priority filtre anahtara dahil edilir)
    cache_key = f"{query}|layer={layer}|priority={doc_priority}"
    t0 = time.monotonic()
    cached = await _redis.get_retrieval(collection, cache_key)
    if cached is not None:
        await _postgres.log_retrieval(
            collection=collection,
            redacted_query=query[:80],
            top1_score=0.0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            hit_count=0,
            query_type="agent_doc:cache_hit",
        )
        return cached

    # Filtre oluştur: temel agent_doc + opsiyonel layer + opsiyonel priority
    must_conditions = list(AGENT_DOC_FILTER.must)  # source_type + is_deleted=False

    if layer:
        must_conditions.append(QFC(key="layer", match=QMV(value=layer)))
    if doc_priority:
        must_conditions.append(QFC(key="doc_priority", match=QMV(value=doc_priority)))

    active_filter = QFilter(must=must_conditions)

    searcher = HybridSearcher(collection=collection)
    results = await searcher.search(query, top_k=8, query_filter=active_filter)

    if not results:
        filter_info = ""
        if layer or doc_priority:
            filter_info = f" (filtre: layer={layer or '*'}, priority={doc_priority or '*'})"
        return f"🔍 Agent dokümanlarda '{query}' için sonuç bulunamadı.{filter_info}"

    # Answerability + context builder
    assessment = assess_answerability(results)
    if assessment.confidence == Confidence.INSUFFICIENT:
        return f"⚠️ Retrieval yetersiz: {assessment.reason}"

    builder = ContextBuilder(token_budget=4000)
    results = builder.build(results)

    output_lines = [f"## '{query}' — Agent Doc Sonuçları ({len(results)} chunk)\n"]
    if assessment.confidence.value == "weak":
        output_lines.append(f"> ⚠️ {assessment.reason}\n")

    for r in results:
        content  = r.get("content", "")
        h1       = r.get("h1", "")
        h2       = r.get("h2", "")
        h3       = r.get("h3", "")
        rel_path = r.get("relative_path", "")
        priority = r.get("doc_priority", "")
        lyr      = r.get("layer", "")

        # Last-mile defense: sonuç içeriğine SecretScanner uygula
        scan = secret_scanner.scan(content)
        safe_content = scan.redacted_text

        heading = " > ".join(x for x in [h1, h2, h3] if x)
        output_lines.append(
            f"### 📄 `{rel_path}`"
            + (f" [{priority}|{lyr}]" if priority or lyr else "")
            + (f" — {heading}" if heading else "")
            + f" (skor: {r.get('score', 0):.3f})\n"
            f"```markdown\n{safe_content[:1000]}\n```\n"
        )

    result_text = "\n".join(output_lines)

    # Cache'e yaz + Postgres log
    await _redis.set_retrieval(collection, cache_key, result_text)
    latency_ms = (time.monotonic() - t0) * 1000
    await _postgres.log_retrieval(
        collection=collection,
        redacted_query=query[:80],
        top1_score=assessment.top1_score,
        latency_ms=int(latency_ms),
        hit_count=len(results),
        query_type="agent_doc",
    )
    return result_text


# --- ARAÇ 7: Episodik Hafızaya Kaydet ---
@app.tool()
async def store_memory(
    title: str,
    content: str,
    memory_type: str = "general",
    tags: list[str] | None = None,
    collection: str = "",
    module: str = "",
    commit_sha: str = "",
    provenance: str = "",
    valid_days: int | None = None, # Faz 3: Kaç gün geçerli olacağı
    status: str = "active",         # active | deprecated | archived
) -> str:
    """
    Sistemin öğrendiği çözüm, mimari karar veya bilinen hatayı episodik hafızaya yazar.
    
    valid_days: Kaç gün sonra bu bilginin geçerliliğini yitireceği (opsiyonel).
    """
    valid_to = None
    if valid_days:
        valid_to = time.time() + (valid_days * 86400)

    entry = MemoryEntry(
        title=title,
        content=content,
        memory_type=memory_type,
        tags=tags or [],
        collection=collection,
        module=module,
        commit_sha=commit_sha,
        provenance=provenance,
        valid_to=valid_to,
        status=status,
    )
    return await _episodic.store_memory(entry)


# --- ARAÇ 8: Episodik Hafızada Ara ---
@app.tool()
async def recall_memory(
    query: str,
    memory_type: str | None = None,
    memory_layer: str | None = None,
    collection: str = "",
    include_invalid: bool = False,
    top_k: int = 5,
) -> str:
    """
    Geçmişte yaşanan çözümleri, mimari kararları veya bilinen hataları arar.
    
    include_invalid: True ise geçerlilik süresi dolmuş veya 'archived' olanları da getirir.
    """
    entries = await _episodic.search_memory(
        query,
        memory_type=memory_type,
        memory_layer=memory_layer,
        collection=collection or None,
        include_invalid=include_invalid,
        top_k=top_k,
    )

    if not entries:
        return "🔍 Episodik hafızada uygun kayıt bulunamadı."

    output = [f"## 🧠 Hafıza Arama: '{query}'\n"]
    for e in entries:
        tags_str = " ".join(f"`{t}`" for t in e.get("tags", []))
        stat_note = ""
        status = e.get("status")
        if status and status != "active":
            stat_note = f" [⚠️ {status.upper()}]"
            
        output.append(
            f"### [{e.get('memory_type','?')}] {e['title']}{stat_note} — skor: {e.get('score',0):.3f}\n"
            + (f"🏷️ {tags_str}\n" if tags_str else "")
            + (f"📦 Koleksiyon: `{e.get('collection','')}`\n" if e.get("collection") else "")
            + (f"🧩 Modül: `{e.get('module','')}`\n" if e.get("module") else "")
            + (f"🔖 Commit: `{e.get('commit_sha','')}`\n" if e.get("commit_sha") else "")
            + f"{e['code'][:600]}\n" # EpisodicStore'da content 'code' payload'una yazılır
        )
    return "\n".join(output)


# --- ARAÇ 16: Hafıza Sıkıştırma (Compaction) ---
@app.tool()
async def compact_memory(collection: str, query: str = "*") -> str:
    """
    Belirli bir koleksiyondaki benzer hafıza kayıtlarını birleştirerek temizlik yapar.
    """
    from src.memory.services.memory_compaction import MemoryCompactor
    compactor = MemoryCompactor(_episodic)
    return await compactor.compact(collection, query)


# --- ARAÇ 17: Agent Görevi Oluştur (Phase 4) ---
@app.tool()
async def create_agent_task(title: str, description: str, collection: str) -> str:
    """
    Uzun süreli bir mühendislik görevi başlatır. Görev durum makinesi tarafından yönetilir.
    """
    task = await _orchestrator.create_task(title, description, collection)
    return f"🚀 Görev başlatıldı! Task ID: `{task.task_id}`\nDurum: `{task.status.value}`"


# --- ARAÇ 18: Görev Durumunu Sorgula (Phase 4) ---
@app.tool()
async def get_task_status(task_id: str) -> str:
    """
    Belirtilen görevin mevcut durumunu ve adımlarını getirir.
    """
    task = await _task_store.get_task(task_id)
    if not task:
        return f"❌ Görev bulunamadı: `{task_id}`"
    
    lines = [
        f"## 📋 Görev: {task.title}",
        f"**ID:** `{task.task_id}`",
        f"**Durum:** `{task.status.value}`",
        f"**Açıklama:** {task.description}",
        "\n### Adımlar:"
    ]
    for i, step in enumerate(task.steps):
        lines.append(f"{i+1}. {step.description} — `{step.status.value}`")
    
    return "\n".join(lines)


# --- ARAÇ 19: Görev Onayı Ver (Phase 4) ---
@app.tool()
async def approve_task_step(task_id: str, feedback: str = "approved") -> str:
    """
    'waiting_approval' durumundaki bir göreve devam etmesi için onay verir.
    """
    return await _orchestrator.approve_task(task_id)


# --- ARAÇ 20: Görevleri Listele (Phase 4) ---
@app.tool()
async def list_agent_tasks(collection: str = "", status: str = "") -> str:
    """
    Sistemdeki kayıtlı görevleri listeler.
    """
    t_status = TaskStatus(status) if status else None
    tasks = await _task_store.list_tasks(collection or None, t_status)
    if not tasks:
        return "ℹ️ Kayıtlı görev bulunamadı."
        
    lines = ["## 📋 Kayıtlı Görevler\n"]
    for t in tasks[:15]:
        lines.append(f"- `{t.task_id[:8]}` | **{t.title}** | `{t.status.value}`")
    
    return "\n".join(lines)


# --- ARAÇ 21: Doğrulama Planı Çalıştır (Phase 5) ---
@app.tool()
async def run_verification_plan(
    project_path: str,
    run_build: bool = True,
    run_tests: bool = True,
    run_lint: bool = False
) -> str:
    """
    Güvenli sandbox ortamında build ve test süreçlerini koşturur.
    Proje tipini otomatik algılar ve uygun komutları seçer.
    """
    profile = _runtime_manager.detect_profile(project_path)
    profile_name = profile.name if profile and profile.name else "UNKNOWN"
    output = [f"## 🛠️ Doğrulama Planı — {profile_name.upper()}\n"]
    
    if run_build:
        output.append(f"### 📦 Build ({profile.build_cmd})")
        res = await _runtime_manager.run_build(project_path)
        output.append(f"**Durum:** {'✅ Başarılı' if res.success else '❌ Başarısız'}")
        if not res.success:
            output.append(f"```text\n{res.stderr or res.stdout[:500]}\n```")
            return "\n".join(output) # Build başarısızsa testi çalıştırma
    
    if run_tests:
        output.append(f"\n### 🧪 Test ({profile.test_cmd})")
        res = await _runtime_manager.run_tests(project_path)
        output.append(f"**Durum:** {'✅ Başarılı' if res.success else '❌ Başarısız'}")
        if res.stdout or res.stderr:
            output.append(f"```text\n{(res.stdout + res.stderr)[:1000]}\n```")

    if run_lint:
        output.append(f"\n### 🧹 Lint ({profile.lint_cmd})")
        res = await _runtime_manager.run_lint(project_path)
        output.append(f"**Durum:** {'✅ Başarılı' if res.success else '❌ Başarısız'}")

    return "\n".join(output)


# --- ARAÇ 22: Retrieval Değerlendirmesi Çalıştır (Phase 6) ---
@app.tool()
async def run_retrieval_eval(dataset_name: str, collection: str) -> str:
    """
    Belirli bir veri seti üzerinden retrieval kalitesini ölçer (Hit@K, MRR).
    """
    dataset = _dataset_manager.load_dataset(dataset_name)
    if not dataset:
        return f"❌ Veri seti bulunamadı: `{dataset_name}`"
    
    # search_code tool'unu runner'a bağla
    runner = EvalRunner(search_code)
    results = await runner.run_eval(dataset, collection)
    
    s = results["summary"]
    lines = [
        f"## 📊 Retrieval Eval — {dataset_name} ({collection})",
        f"- **Toplam Case:** {s['total_cases']}",
        f"- **Hit@1:** {s['hit_at_1']:.1%}",
        f"- **Hit@3:** {s['hit_at_3']:.1%}",
        f"- **Hit@5:** {s['hit_at_5']:.1%}",
        f"- **MRR:** {s['mrr']:.3f}",
        f"- **Ort. Gecikme:** {s['avg_latency_sec']:.2f}s",
        "\n> Eval tamamlandı. Sistem performansı veri odaklı olarak ölçüldü."
    ]
    return "\n".join(lines)


# --- ARAÇ 23: Control Plane İstatistikleri (Phase 6) ---
@app.tool()
async def get_control_plane_stats() -> str:
    """
    Model kullanım maliyetleri, latency ve başarı oranlarını getirir.
    """
    stats = _model_gateway.get_stats()
    lines = [
        "## 🕹️ Control Plane — Model Gateway Stats",
        f"- **Toplam Çağrı:** {stats['total_calls']}",
        f"- **Toplam Token:** {stats['total_tokens']}",
        f"- **Top. Gecikme:** {stats['total_latency_ms'] / 1000:.1f}s",
        "\n### Model Bazlı Detaylar:"
    ]
    for model, m_stats in stats["per_model_stats"].items():
        lines.append(f"- **{model}:** {m_stats['calls']} çağrı | {m_stats['tokens']} token | {m_stats['avg_latency']:.0f}ms avg")
    
    return "\n".join(lines)


# --- Placeholder Task Handlers (Phase 4) ---
async def _dummy_handler(task: Task):
    # Bu basit handler sadece status'u bir sonrakine taşır.
    # Gerçek implementasyonda LLM planner/retriever/editor devreye girecek.
    transitions = {
        TaskStatus.PLANNED: TaskStatus.RETRIEVING,
        TaskStatus.RETRIEVING: TaskStatus.ANALYZING,
        TaskStatus.ANALYZING: TaskStatus.WAITING_APPROVAL,
        TaskStatus.EXECUTING: TaskStatus.VERIFYING,
        TaskStatus.VERIFYING: TaskStatus.SUMMARIZING,
        TaskStatus.SUMMARIZING: TaskStatus.DONE,
    }
    next_status = transitions.get(task.status, TaskStatus.DONE)
    return f"{task.status.value} tamamlandı.", next_status

for status in [TaskStatus.PLANNED, TaskStatus.RETRIEVING, TaskStatus.ANALYZING, 
                TaskStatus.EXECUTING, TaskStatus.VERIFYING, TaskStatus.SUMMARIZING]:
    _orchestrator.register_handler(status, _dummy_handler)


# --- ARAÇ 9: Proje Kaydet / Onboard Et ---
@app.tool()
async def register_project(
    project_path: str,
    collection: str = "",
    index_code: bool = True,
    index_docs: bool = True,
    batch_size: int = 32,
) -> str:
    """
    Yeni bir projeyi GraphRagMCP'ye kaydeder.

    V2 foundation:
      - proje profili çıkarılır
      - registry'ye yazılır
      - istenirse kod ve agent docs indekslenir
      - repo summary katmanı oluşturulur
    """
    profile = build_project_profile(project_path, collection=collection)
    _registry.upsert(profile)

    results = [format_profile(profile)]

    if index_code:
        results.append(await index_project(project_path=project_path, collection=profile.collection, batch_size=batch_size))
    else:
        await _sync_project_foundation(project_path, profile.collection)

    if index_docs:
        agent_dir = Path(project_path).resolve() / ".agent"
        if agent_dir.exists():
            results.append(await index_agent_docs(project_path=project_path))
        else:
            results.append("ℹ️ .agent/ dizini bulunmadı; agent doc indeksleme atlandı.")

    return "\n\n".join(results)


# --- ARAÇ 10: Kayıtlı Projeleri Listele ---
@app.tool()
async def list_projects() -> str:
    profiles = _registry.list_profiles()
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


# --- ARAÇ 11: Repository Summary Üret ---
@app.tool()
async def summarize_repository(project_path: str, collection: str = "") -> str:
    profile = await sync_project_intelligence(project_path, collection=collection, redis_store=_redis)
    _registry.upsert(profile)
    return format_profile(profile)


# --- ARAÇ 12: Repo Mimarisinde Ara ---
@app.tool()
async def search_repo_architecture(
    query: str,
    collection: str = "",
    top_k: int = 6,
) -> str:
    collection = collection or os.getenv("DEFAULT_COLLECTION", "codebase")

    architecture_filter = QFilter(
        must=[QFC(key="source_type", match=QMV(value="repo_summary"))]
    )
    searcher = HybridSearcher(collection=collection)
    results = await searcher.search(query, top_k=top_k, fetch_k=max(top_k * 2, 10), query_filter=architecture_filter)

    if not results:
        return "🔍 Repository architecture summary bulunamadı. Önce summarize_repository veya index_project çalıştırın."

    output = [f"## Repository Architecture — `{query}` ({collection})\n"]
    for item in results:
        output.append(
            f"### `{item.get('name','')}` ({item.get('type','')}) — skor: {item.get('score', 0):.3f}\n"
            f"{item.get('code','')[:1200]}\n"
        )
    return "\n".join(output)


# --- ARAÇ 13: Değişiklik Etki Analizi ---
@app.tool()
async def analyze_change_impact(
    project_path: str,
    changed_paths: list[str],
    collection: str = "",
) -> str:
    """
    Değişen dosyaların projenin geri kalanı üzerindeki etkisini analiz eder.
    Neo4j graph verisini kullanarak 3 seviye derinliğe kadar çağrı zincirini takip eder.
    """
    collection = collection or _project_collection_name(project_path)
    normalized, rejected = _normalize_changed_files(
        project_path,
        changed_paths,
        SUPPORTED_SOURCE_EXTENSIONS,
        EXCLUDE_DIRS,
    )

    if not normalized:
        return "⚠️ Analiz edilecek geçerli bir dosya yolu bulunamadı."

    # Yeni gelişmiş analiz motorunu çalıştır
    results = await _impact_analyzer.analyze(collection, normalized)
    
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
            lines.append("**İçerik:** " + ", ".join(f"`{e['name']}` ({e['type'] or 'entity'})" for e in data["entities"][:10]))
        
        if data["callers"]:
            lines.append("\n**Etkilenen Çağrıcılar (Callers):**")
            for c in data["callers"][:12]:
                dist_note = " (doğrudan)" if c["distance"] == 1 else f" ({c['distance']} seviye)"
                lines.append(f"  - `{c['name']}`{dist_note} → `{Path(c.get('file_path', '')).name}`")
        else:
            lines.append("\n**Dış çağrıcı bulunamadı.**")

        if data["dependencies"]:
            lines.append("\n**Bağımlılıklar (Uses):**")
            for d in data["dependencies"][:8]:
                lines.append(f"  - `{d['name']}`")
        
        lines.append("")

    if rejected:
        lines.append("\n---\n**Atlanan Yollar:** " + ", ".join(f"`{r}`" for r in rejected[:10]))

    return "\n".join(lines)


# --- ARAÇ 14: Karar Hafızasına Yaz ---
@app.tool()
async def store_decision_memory(
    title: str,
    content: str,
    collection: str,
    module: str = "",
    commit_sha: str = "",
    provenance: str = "",
    tags: list[str] | None = None,
) -> str:
    entry = MemoryEntry(
        title=title,
        content=content,
        memory_type="decision",
        tags=tags or [],
        collection=collection,
        module=module,
        commit_sha=commit_sha,
        provenance=provenance,
    )
    return await _episodic.store_memory(entry)


# --- ARAÇ 15: Karar Hafızasında Ara ---
@app.tool()
async def search_decisions(
    query: str,
    collection: str = "",
    top_k: int = 5,
) -> str:
    entries = await _episodic.search_memory(
        query,
        memory_layer="decision",
        collection=collection or None,
        top_k=top_k,
    )
    if not entries:
        return "🔍 Karar hafızasında uygun kayıt bulunamadı."

    output = [f"## Karar Hafızası — '{query}'\n"]
    for item in entries:
        output.append(
            f"### {item.get('title','')} — skor: {item.get('score', 0):.3f}\n"
            + (f"📦 Koleksiyon: `{item.get('collection','')}`\n" if item.get("collection") else "")
            + (f"🧩 Modül: `{item.get('module','')}`\n" if item.get("module") else "")
            + (f"🔖 Commit: `{item.get('commit_sha','')}`\n" if item.get("commit_sha") else "")
            + f"{item.get('content','')[:800]}\n"
        )
    return "\n".join(output)


if __name__ == "__main__":
    app.run(transport="stdio")
