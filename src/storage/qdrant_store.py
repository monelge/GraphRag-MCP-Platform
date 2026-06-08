from __future__ import annotations
import logging
import time
import uuid
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams,
    SparseIndexParams, PointStruct, SparseVector,
    FieldCondition, Filter, MatchValue,
    PayloadSchemaType, PointIdsList,
)
from src.shared.config import config
from src.indexing.chunkers.chunk_models import CodeChunk, AgentDocChunk

from src.shared.logging_config import get_logger
logger = get_logger(__name__)


class QdrantStore:
    def __init__(self, collection: str | None = None):
        # Her proje kendi koleksiyonuna sahip olur; ad proje dizin adından gelir.
        self.collection = collection or config.default_collection
        logger.debug("Initializing QdrantStore collection=%s url=%s", self.collection, config.qdrant_url)
        try:
            api_key = config.qdrant_api_key or None
            self.client = AsyncQdrantClient(
                url=config.qdrant_url,
                api_key=api_key,
            )
        except Exception as exc:
            logger.error("Qdrant AsyncQdrantClient initialization failed: %s", exc)
            raise

    async def ensure_collection(self):
        """
        Koleksiyonu oluşturur. Varsa dokunmaz.
        Dense + Sparse vektörler aynı koleksiyonda yaşar — hibrit arama budur.
        """
        t0 = time.monotonic()
        try:
            existing = await self.client.get_collections()
            names = [c.name for c in existing.collections]
            # Case-insensitive eşleşme: warelogisticcbys ↔ WareLogisticcBYS
            match = next((n for n in names if n.lower() == self.collection.lower()), None)
            if match and match != self.collection:
                logger.info("Qdrant collection case uyumsuz, mevcut isim kullanılıyor",
                            extra={"requested": self.collection, "actual": match})
                self.collection = match
            if self.collection not in names and not match:
                logger.info("Qdrant collection yok, oluşturuluyor", extra={"collection": self.collection})
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config={
                        "dense": VectorParams(size=config.embedding_dim, distance=Distance.COSINE),
                    },
                    sparse_vectors_config={
                        "sparse": SparseVectorParams(
                            index=SparseIndexParams(on_disk=False)
                        ),
                    },
                )
                for field_name in ("source_type", "layer", "doc_priority", "is_deleted", "relative_path", "chunk_type", "project_name"):
                    await self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field_name,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                latency = int((time.monotonic() - t0) * 1000)
                logger.info("Qdrant collection başarıyla oluşturuldu", extra={"collection": self.collection, "latency_ms": latency})
            else:
                logger.debug("Qdrant collection zaten mevcut", extra={"collection": self.collection})
        except Exception as exc:
            logger.error("Qdrant collection doğrulama/oluşturma hatası", exc_info=True, extra={"collection": self.collection, "error": str(exc)})
            raise

    async def get_indexed_file_paths(self) -> set[str]:
        """Qdrant'ta zaten indekslenmiş dosya yollarını döndürür."""
        indexed: set[str] = set()
        offset = None

        while True:
            result = await self.client.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                with_payload=["file_path"],
                with_vectors=False,
            )
            points, next_offset = result

            for point in points:
                fp = (point.payload or {}).get("file_path")
                if fp:
                    indexed.add(fp)

            if next_offset is None:
                break
            offset = next_offset

        return indexed

    async def upsert_chunks(
        self,
        chunks: list[CodeChunk],
        dense_vecs: list[list[float]],
        sparse_vecs,
        extra_payload: dict | None = None,
    ):
        """Chunk'ları hem dense hem sparse vektörleriyle birlikte Qdrant'a yazar."""
        t0 = time.monotonic()
        points = []
        for chunk, dense, sparse in zip(chunks, dense_vecs, sparse_vecs):
            payload = chunk.to_dict()
            # Arama filtreleri (CODE_ONLY_FILTER) için source_type=code zorunludur.
            if "source_type" not in payload:
                payload["source_type"] = "code"
            
            if extra_payload:
                payload.update(extra_payload)

            points.append(PointStruct(
                id=self._chunk_id_to_point_id(chunk.chunk_id),
                vector={
                    "dense":  dense,
                    "sparse": SparseVector(
                        indices=sparse.indices.tolist(),
                        values=sparse.values.tolist(),
                    ),
                },
                payload=payload,
            ))
        chunk_count = len(points)
        logger.info("Qdrant code chunk'ları yazma işlemi başlatılıyor", extra={"collection": self.collection, "chunk_count": chunk_count})
        try:
            await self.client.upsert(collection_name=self.collection, points=points)
            latency = int((time.monotonic() - t0) * 1000)
            logger.info("Qdrant code chunk'ları başarıyla yazıldı", extra={"collection": self.collection, "chunk_count": chunk_count, "latency_ms": latency})
        except Exception as exc:
            logger.error("Qdrant code chunk'ları yazma hatası", exc_info=True, extra={"collection": self.collection, "chunk_count": chunk_count, "error": str(exc)})
            raise

    @staticmethod
    def _chunk_id_to_point_id(chunk_id: str) -> str:
        """chunk_id (SHA256 hex) → Qdrant UUID point ID."""
        import uuid as _uuid
        NAMESPACE_GRAPH_MCP = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(_uuid.uuid5(NAMESPACE_GRAPH_MCP, chunk_id))

    async def upsert_agent_doc_chunks(
        self,
        chunks: list[AgentDocChunk],
        dense_vecs: list[list[float]],
        sparse_vecs,
    ) -> None:
        """Agent doc chunk'larını Qdrant'a yazar."""
        t0 = time.monotonic()
        points = []
        for chunk, dense, sparse in zip(chunks, dense_vecs, sparse_vecs):
            points.append(PointStruct(
                id=self._chunk_id_to_point_id(chunk.chunk_id),
                vector={
                    "dense":  dense,
                    "sparse": SparseVector(
                        indices=sparse.indices.tolist(),
                        values=sparse.values.tolist(),
                    ),
                },
                payload={
                    "source_type":              chunk.source_type,
                    "chunk_id":                 chunk.chunk_id,
                    "checksum":                 chunk.checksum,
                    "relative_path":            chunk.relative_path,
                    "content":                  chunk.content,
                    "h1":                       chunk.h1,
                    "h2":                       chunk.h2,
                    "h3":                       chunk.h3,
                    "doc_priority":             chunk.doc_priority,
                    "required_on_session_start": chunk.required_on_session_start,
                    "layer":                    chunk.layer,
                    "schema_version":           chunk.schema_version,
                    "is_deleted":               chunk.is_deleted,
                    "updated_at":               chunk.updated_at,
                },
            ))
        chunk_count = len(points)
        logger.info("Qdrant agent doc chunk'ları yazma işlemi başlatılıyor", extra={"collection": self.collection, "chunk_count": chunk_count})
        try:
            await self.client.upsert(collection_name=self.collection, points=points)
            latency = int((time.monotonic() - t0) * 1000)
            logger.info("Qdrant agent doc chunk'ları başarıyla yazıldı", extra={"collection": self.collection, "chunk_count": chunk_count, "latency_ms": latency})
        except Exception as exc:
            logger.error("Qdrant agent doc chunk'ları yazma hatası", exc_info=True, extra={"collection": self.collection, "chunk_count": chunk_count, "error": str(exc)})
            raise

    async def get_agent_doc_chunks_by_path(self, relative_path: str) -> list[dict]:
        """Verilen relative_path için Qdrant'taki mevcut agent_doc chunk'larını döndürür."""
        results: list[dict] = []
        offset = None

        doc_filter = Filter(must=[
            FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
            FieldCondition(key="relative_path", match=MatchValue(value=relative_path)),
        ])

        while True:
            points, next_offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=doc_filter,
                limit=200,
                offset=offset,
                with_payload=["chunk_id", "checksum"],
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                results.append({
                    "point_id": str(point.id),
                    "chunk_id": payload.get("chunk_id", ""),
                    "checksum": payload.get("checksum", ""),
                })
            if next_offset is None:
                break
            offset = next_offset

        return results

    async def get_all_agent_doc_paths(self) -> set[str]:
        """Koleksiyondaki tüm agent_doc chunk'larının relative_path değerlerini döndürür."""
        paths: set[str] = set()
        offset = None

        doc_filter = Filter(must=[
            FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
        ])

        while True:
            points, next_offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=doc_filter,
                limit=1000,
                offset=offset,
                with_payload=["relative_path"],
                with_vectors=False,
            )
            for point in points:
                rp = (point.payload or {}).get("relative_path")
                if rp:
                    paths.add(rp)
            if next_offset is None:
                break
            offset = next_offset

        return paths

    async def delete_chunks_by_point_ids(self, point_ids: list[str]) -> None:
        """UUID point ID listesine göre chunk'ları fiziksel olarak siler."""
        if not point_ids:
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=point_ids),
        )

    async def delete_by_filter(self, filter_obj: Filter) -> int:
        """Bir filter'e uyan tüm noktaları fiziksel olarak siler."""
        point_ids: list[str] = []
        offset = None
        while True:
            points, next_offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=filter_obj,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            for p in points:
                point_ids.append(str(p.id))
            if next_offset is None or not points:
                break
            offset = next_offset

        if point_ids:
            await self.client.delete(
                collection_name=self.collection,
                points_selector=PointIdsList(points=point_ids),
            )
        return len(point_ids)

    async def tombstone_chunks_by_path(self, relative_path: str) -> None:
        """Silinen dosyanın chunk'larına is_deleted=True yazar."""
        tombstone_filter = Filter(must=[
            FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
            FieldCondition(key="relative_path", match=MatchValue(value=relative_path)),
        ])
        await self.client.set_payload(
            collection_name=self.collection,
            payload={"is_deleted": True},
            points=tombstone_filter,
        )
