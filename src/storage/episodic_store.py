"""
Episodic Memory Store — Sistemin geçmiş deneyimlerini saklar ve sorgular.

Retrieval DB (Qdrant) ≠ Memory DB:
  - Qdrant: kaynak kodu ve doküman retrieval için
  - Episodic Store: öğrenilmiş deneyimler için (ayrı koleksiyon)

Saklanan deneyim tipleri:
  resolved_incident   — Çözülmüş sorunlar (bug, outage, edge case)
  architecture_decision — Tasarım kararları ve gerekçeleri
  known_bug           — Bilinen hatalar ve geçici çözümler
  production_fix      — Production düzeltmeleri
  migration_note      — Migration / upgrade notları
  auth_edge_case      — Auth & güvenlik köşe durumları

Neden ayrı koleksiyon?
  Kod araması ile deneyim araması farklı precision/recall hedefleri taşır.
  Karıştırılmaları false positive üretir.
"""

from __future__ import annotations
import hashlib
import os
import time
import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

"""
Memory taxonomy — 4 katman:

  Semantic (SemanticKnowledge):
    Mimari kurallar, domain bilgisi, proje kararları
    Örnekler: "Vendoris auth JWT kullaniyor", "Tüm API'ler /api/v1 prefix alır"

  Episodic:
    Geçmiş çözümler, yaşanan olaylar, debug deneyimi
    Örnekler: "Login sonrası 401 — refresh token süresi dolmuştu"

  Procedural:
    Adım adım işlem talimatları: deployment, build, migration
    Örnekler: "Production deploy: önce migration, sonra container restart"

  Decision:
    Neden X seçildi, alternatiflerin neden reddedildiği
    Örnekler: "Redis cache seçildi çünkü Postgres latency >50ms idi"

Tek Qdrant koleksiyonu + memory_layer metadata filter kullanılır.
(4 ayrı koleksiyon gereksiz karmaşıklık yaratır; layer filtresi yeterli.)
"""

MemoryLayer = Literal[
    "semantic",     # Mimari/domain bilgisi
    "episodic",     # Geçmiş çözümler ve olaylar
    "procedural",   # Adım adım prosedürler
    "decision",     # Neden X seçildi kararları
]

# Geriye dönük uyumluluk — eski memory_type alanları hâlâ desteklenir
MemoryType = Literal[
    "resolved_incident",
    "architecture_decision",
    "known_bug",
    "production_fix",
    "migration_note",
    "auth_edge_case",
]

# eski memory_type → yeni layer eşlemesi
_MEMORY_TYPE_TO_LAYER: dict[str, str] = {
    "resolved_incident":    "episodic",
    "architecture_decision":"decision",
    "known_bug":            "episodic",
    "production_fix":       "procedural",
    "migration_note":       "procedural",
    "auth_edge_case":       "episodic",
    # Yeni doğrudan layer değerleri
    "semantic":    "semantic",
    "episodic":    "episodic",
    "procedural":  "procedural",
    "decision":    "decision",
    "general":     "episodic",  # varsayılan
}

# Episodic memory için ayrı Qdrant koleksiyonu
_MEMORY_COLLECTION = "episodic_memory"


@dataclass
class MemoryEntry:
    """Tek bir bellek kaydı — taxonomy ve Task linkage dahil."""
    title: str
    content: str
    memory_type: str = "episodic"   # MemoryType veya MemoryLayer değeri
    tags: list[str] = field(default_factory=list)
    collection: str = ""
    module: str = ""
    commit_sha: str = ""
    provenance: str = ""
    # Faz 3: Temporal Facts & Validity
    valid_from: Optional[float] = None  # UNIX timestamp
    valid_to: Optional[float] = None    # UNIX timestamp
    status: str = "active"              # active | deprecated | archived
    
    # Faz 3: Memory-Agent Link
    task_id: str = ""                   # İlgili Task ID (varsa)
    checkpoint_id: str = ""             # İlgili Checkpoint ID (varsa)
    step_id: str = ""                   # İlgili TaskStep ID (varsa)
    
    # Otomatik doldurulur
    entry_id: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = hashlib.sha256(
                f"{self.title}:{self.content[:200]}".encode()
            ).hexdigest()[:16]
        if not self.created_at:
            self.created_at = time.time()
            if self.valid_from is None:
                self.valid_from = self.created_at

    @property
    def memory_layer(self) -> str:
        """Taxonomy katmanını döner (semantic/episodic/procedural/decision)."""
        return _MEMORY_TYPE_TO_LAYER.get(self.memory_type, "episodic")

    @property
    def is_valid(self) -> bool:
        """Belleğin şu an geçerli olup olmadığını kontrol eder."""
        now = time.time()
        if self.status != "active":
            return False
        if self.valid_to and now > self.valid_to:
            return False
        return True


class EpisodicStore:
    """
    Episodik bellek deposu — Qdrant üzerinde ayrı koleksiyon.
    DenseEmbedder / SparseEmbedder bağımlılığından kaçınmak için
    lazy import kullanır.
    """

    def __init__(self):
        self._collection = _MEMORY_COLLECTION

    async def _get_store(self):
        """QdrantStore'u lazy olarak oluşturur."""
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore(collection=self._collection)
        await store.ensure_collection()
        return store

    async def _get_embedders(self, redis_store=None):
        from src.indexing.embedders.dense_embedder import DenseEmbedder
        from src.indexing.embedders.sparse_embedder import SparseEmbedder
        return DenseEmbedder(redis_store=redis_store), SparseEmbedder()

    async def store_memory(self, entry: MemoryEntry, redis_store=None) -> str:
        """
        Yeni bir episodik bellek kaydı oluşturur.
        Aynı entry_id zaten varsa günceller (idempotent).
        """
        try:
            store = await self._get_store()
            dense, sparse = await self._get_embedders(redis_store)

            text = f"{entry.title}\n\n{entry.content}"
            dense_vecs = await dense.embed_batch([text])
            sparse_vecs = list(sparse.embed_batch([text]))

            # Chunk benzeri payload oluştur — qdrant_store.upsert_chunks ile uyumlu
            from src.indexing.chunkers.chunk_models import CodeChunk
            pseudo_chunk = CodeChunk(
                chunk_id=entry.entry_id,
                file_path=f"memory://{entry.memory_type}/{entry.entry_id}",
                language="markdown",
                chunk_type=entry.memory_type,
                name=entry.title,
                code=entry.content,
                start_line=0,
                end_line=0,
            )
            # payload'a memory metadata, layer ve task linkage ekle
            await store.upsert_chunks(
                [pseudo_chunk], dense_vecs, sparse_vecs,
                extra_payload={
                    "memory_type": entry.memory_type,
                    "memory_layer": entry.memory_layer,
                    "tags": entry.tags,
                    "collection": entry.collection,
                    "module": entry.module,
                    "commit_sha": entry.commit_sha,
                    "provenance": entry.provenance,
                    "created_at": entry.created_at,
                    "valid_from": entry.valid_from,
                    "valid_to": entry.valid_to,
                    "status": entry.status,
                    "source_type": "episodic_memory",
                    # Faz 3: Task Linkage
                    "task_id": entry.task_id,
                    "checkpoint_id": entry.checkpoint_id,
                    "step_id": entry.step_id,
                }
            )
            return f"✅ Bellek kaydı oluşturuldu: {entry.entry_id} ({entry.memory_type}/{entry.memory_layer})"
        except Exception as e:
            logger.error("EpisodicStore.store_memory hata: %s", e)
            return f"⚠️ Bellek kaydı oluşturulamadı: {e}"

    async def search_memory(
        self,
        query: str,
        memory_type: str | None = None,
        memory_layer: str | None = None,
        collection: str | None = None,
        include_invalid: bool = False,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Bellek koleksiyonunda hibrit arama yapar.

        Filtreler (ikisi de opsiyonel):
          memory_type: eski tip değerleri (resolved_incident, known_bug, ...)
          memory_layer: taxonomy katmanı (semantic/episodic/procedural/decision)
          include_invalid: True ise status != 'active' olanları da getirir.
        """
        try:
            from src.retrieval.search.hybrid_search import HybridSearcher
            from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

            searcher = HybridSearcher(collection=self._collection)

            must_conditions = [
                FieldCondition(
                    key="source_type",
                    match=MatchValue(value="episodic_memory"),
                )
            ]

            # Varsayılan olarak sadece 'active' olanları getir
            if not include_invalid:
                must_conditions.append(
                    FieldCondition(
                        key="status",
                        match=MatchValue(value="active"),
                    )
                )
                # Geçerlilik süresi kontrolü (valid_to > now veya valid_to is None)
                # Not: Qdrant'ta None kontrolü için 'should' veya 'must_not' gerekebilir.
                # Şimdilik basitleştirelim: status='active' yeterli bir ilk sinyal.

            # Layer filtresi — önce memory_layer'a bak, yoksa memory_type'dan çevir
            effective_layer = memory_layer
            if not effective_layer and memory_type:
                effective_layer = _MEMORY_TYPE_TO_LAYER.get(memory_type)

            if effective_layer:
                must_conditions.append(
                    FieldCondition(
                        key="memory_layer",
                        match=MatchValue(value=effective_layer),
                    )
                )
            elif memory_type:
                # layer çevrilemedi → direkt memory_type filtrele
                must_conditions.append(
                    FieldCondition(
                        key="memory_type",
                        match=MatchValue(value=memory_type),
                    )
                )

            if collection:
                must_conditions.append(
                    FieldCondition(
                        key="collection",
                        match=MatchValue(value=collection),
                    )
                )

            query_filter = Filter(must=must_conditions)
            results = await searcher.search(query, top_k=top_k, query_filter=query_filter)
            return results
        except Exception as e:
            logger.debug("EpisodicStore.search_memory hata: %s", e)
            return []
