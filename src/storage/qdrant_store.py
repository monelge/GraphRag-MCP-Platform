from __future__ import annotations
import os
import uuid
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams,
    SparseIndexParams, PointStruct, SparseVector,
    ScrollRequest, FieldCondition, Filter, MatchAny, MatchValue,
    PayloadSchemaType, PointIdsList,
    SetPayload,
)
from src.indexing.chunkers.chunk_models import CodeChunk, AgentDocChunk

DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


class QdrantStore:
    def __init__(self, collection: str = "codebase"):
        # Her proje kendi koleksiyonuna sahip olur; ad proje dizin adından gelir.
        self.collection = collection
        self.client = AsyncQdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
        )

    async def ensure_collection(self):
        """
        Koleksiyonu oluşturur. Varsa dokunmaz.
        Dense + Sparse vektörler aynı koleksiyonda yaşar — hibrit arama budur.
        Payload index'leri de burada oluşturulur; source_type, layer, doc_priority
        ve is_deleted sık filtrelenen alanlardır.
        """
        existing = await self.client.get_collections()
        names = [c.name for c in existing.collections]
        if self.collection not in names:
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config={
                    "dense": VectorParams(size=DIM, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(
                        index=SparseIndexParams(on_disk=False)
                    ),
                },
            )
            # Sık filtrelenen alanlar için payload index — küçük ölçekte opsiyonel
            # ama tutarlılık için şimdi tanımlanır
            for field_name in ("source_type", "layer", "doc_priority", "is_deleted", "relative_path", "chunk_type", "project_name"):
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )

    async def get_indexed_file_paths(self) -> set[str]:
        """
        Qdrant'ta zaten indekslenmiş dosya yollarını döndürür.
        Resume desteği için kullanılır — bu dosyalar atlanır.
        Scroll API ile tüm payload'ları tarar; büyük koleksiyonlarda
        offset tabanlı sayfalama ile çalışır.
        """
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

            # next_offset None ise tüm kayıtlar okundu
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
        """
        Chunk'ları hem dense hem sparse vektörleriyle birlikte Qdrant'a yazar.
        Payload olarak ham kodu ve meta veriyi de saklarız — arama sonucunda
        doğrudan orijinal koda erişmek için.
        """
        points = []
        for chunk, dense, sparse in zip(chunks, dense_vecs, sparse_vecs):
            # CodeChunk to_dict ile tüm provenance metadata'yı alıyoruz
            payload = chunk.to_dict()
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
        await self.client.upsert(collection_name=self.collection, points=points)

    # ------------------------------------------------------------------
    # Agent Doc metodları — source_type='agent_doc' chunk'ları
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_id_to_point_id(chunk_id: str) -> str:
        """
        chunk_id (SHA256 hex) → Qdrant UUID point ID.
        """
        # SHA256 hex string'ini stabil bir UUID'ye dönüştürmenin en güvenli yolu
        # namespace tabanlı UUID5 kullanmaktır.
        import uuid as _uuid
        NAMESPACE_GRAPH_MCP = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(_uuid.uuid5(NAMESPACE_GRAPH_MCP, chunk_id))

    async def upsert_agent_doc_chunks(
        self,
        chunks: list[AgentDocChunk],
        dense_vecs: list[list[float]],
        sparse_vecs,
    ) -> None:
        """
        Agent doc chunk'larını Qdrant'a yazar.
        source_type='agent_doc' payload alanı ile kod chunk'larından ayrılır;
        bu sayede search_code() ve search_agent_docs() birbirinin sonuçlarına karışmaz.
        """
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
        await self.client.upsert(collection_name=self.collection, points=points)

    async def get_agent_doc_chunks_by_path(self, relative_path: str) -> list[dict]:
        """
        Verilen relative_path için Qdrant'taki mevcut agent_doc chunk'larını döndürür.
        Her kayıt: {point_id (UUID str), chunk_id, checksum}

        Neden bu metot?
          index_agent_docs()'un incremental sync'i için disk checksum'u ile
          Qdrant checksum'u karşılaştırmak gerekir. Değişmeyen chunk'lar
          yeniden embed edilmez — token + zaman tasarrufu.
        """
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
        """
        Koleksiyondaki tüm agent_doc chunk'larının relative_path değerlerini döndürür.
        index_agent_docs() sonunda silinmiş dosyaları tespit etmek için kullanılır:
          disk_paths - qdrant_paths = tombstone edilmesi gereken yollar
        """
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
        """
        UUID point ID listesine göre chunk'ları fiziksel olarak siler.
        Atomic two-phase sync'in ikinci adımı: yeni chunk'lar başarıyla
        yüklendikten sonra eski chunk'lar bu metotla silinir.
        """
        if not point_ids:
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=point_ids),
        )

    async def tombstone_chunks_by_path(self, relative_path: str) -> None:
        """
        Silinen dosyanın chunk'larına is_deleted=True yazar.
        Neden tombstone, fiziksel silme değil?
          30 gün içinde arama yapılırsa eski içerik is_deleted filtresiyle
          hariç tutulur; veri kaybı yaşanmaz. 30 gün sonra purge çalışabilir.
        """
        tombstone_filter = Filter(must=[
            FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
            FieldCondition(key="relative_path", match=MatchValue(value=relative_path)),
        ])
        await self.client.set_payload(
            collection_name=self.collection,
            payload={"is_deleted": True},
            points=tombstone_filter,
        )
