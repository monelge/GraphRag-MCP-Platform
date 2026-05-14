from __future__ import annotations
from qdrant_client.models import (
    SparseVector,
    Prefetch,
    FusionQuery,
    Fusion,
    Filter,
    FieldCondition,
    MatchValue,
)
from src.storage.qdrant_store import QdrantStore
from src.indexing.embedders.dense_embedder import DenseEmbedder
from src.indexing.embedders.sparse_embedder import SparseEmbedder


# source_type='agent_doc' chunk'larını kod aramalarından dışlayan sabit filtre.
# Neden gerekli?
#   index_agent_docs() ve index_project() aynı Qdrant koleksiyonuna yazar.
#   search_code() / explain_code() yalnızca kaynak kodu bulmalıdır;
#   agent doc chunk'ları (name/language/start_line alanları yok) bu arama için
#   anlamsız ve KeyError üretir.
CODE_ONLY_FILTER = Filter(
    must_not=[
        FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
        FieldCondition(key="source_type", match=MatchValue(value="repo_summary")),
        FieldCondition(key="source_type", match=MatchValue(value="episodic_memory")),
    ]
)

# search_agent_docs() için temel filtre — is_deleted=True tombstone'lar dahil değil
AGENT_DOC_FILTER = Filter(
    must=[
        FieldCondition(key="source_type", match=MatchValue(value="agent_doc")),
        FieldCondition(key="is_deleted", match=MatchValue(value=False)),
    ]
)


class HybridSearcher:
    """
    Neden hibrit?
    - Sadece dense: "SHA256" token'ını bulamayabilir (anlam ≠ kelime)
    - Sadece BM25: "kullanıcı doğrulama" → "authenticate user" eşleşmez
    - İkisi birlikte: RRF (Reciprocal Rank Fusion) her iki listenin
      sıralamalarını birleştirerek en isabetli sonucu üretir.
    """

    def __init__(self, collection: str = "codebase", top_k_fetch: int = 20):
        self.store  = QdrantStore(collection=collection)
        self.dense  = DenseEmbedder()
        self.sparse = SparseEmbedder()

    async def search(self, query: str, top_k: int = 10, query_filter=None, fetch_k: int | None = None) -> list[dict]:
        # 1. Sorguyu iki farklı vektör formatına çevir
        dense_vec  = (await self.dense.embed_batch([query]))[0]
        sparse_vec = list(self.sparse.embed_batch([query]))[0]

        # 2. Qdrant'ın yerleşik RRF Fusion özelliğiyle hibrit sorgu gönder
        results = await self.store.client.query_points(
            collection_name=self.store.collection,
            prefetch=[
                # Dense branch: anlamsal benzerlik (top 20 aday)
                Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=20,
                ),
                # Sparse branch: BM25 anahtar kelime (top 20 aday)
                Prefetch(
                    query=SparseVector(
                        indices=sparse_vec.indices.tolist(),
                        values=sparse_vec.values.tolist(),
                    ),
                    using="sparse",
                    limit=20,
                ),
            ],
            # RRF: iki listenin sıralamasını birleştirir, ağırlık gerekmez
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=query_filter,
            limit=fetch_k or max(top_k * 2, 20),
            with_payload=True,
        )

        return [
            self._format_hit(hit)
            for hit in results.points
        ]

    @staticmethod
    def _format_hit(hit) -> dict:
        """
        Qdrant point'ini tip-bağımsız dict'e dönüştürür.
        source_type alanına göre farklı yapı döndürür:
          - 'agent_doc': markdown metadata alanları
          - diğer (source_code / None): mevcut kod alanları
        Neden ayrı metot?
          search() başka source_type'lar için genişletilebilir kalır.
        """
        payload = hit.payload or {}
        score = hit.score
        source_type = payload.get("source_type", "source_code")

        if source_type == "agent_doc":
            return {
                "score":        score,
                "source_type":  "agent_doc",
                "relative_path": payload.get("relative_path", ""),
                "content":      payload.get("content", ""),
                "h1":           payload.get("h1", ""),
                "h2":           payload.get("h2", ""),
                "h3":           payload.get("h3", ""),
                "layer":        payload.get("layer", ""),
                "doc_priority": payload.get("doc_priority", ""),
                "chunk_id":     payload.get("chunk_id", ""),
                # Geriye dönük uyum: search_agent_docs payload erişimi için
                "payload":      payload,
            }

        if source_type == "repo_summary":
            return {
                "score": score,
                "source_type": "repo_summary",
                "file": payload.get("file_path", ""),
                "name": payload.get("name", ""),
                "type": payload.get("chunk_type", ""),
                "code": payload.get("code", ""),
                "lines": f"{payload.get('start_line', 0)}-{payload.get('end_line', 0)}",
                "language": payload.get("language", "markdown"),
                "project_name": payload.get("project_name", ""),
                "payload": payload,
            }

        if source_type == "episodic_memory":
            return {
                "score": score,
                "source_type": "episodic_memory",
                "title": payload.get("name", ""),
                "content": payload.get("code", ""),
                "memory_type": payload.get("memory_type", ""),
                "memory_layer": payload.get("memory_layer", ""),
                "tags": payload.get("tags", []),
                "collection": payload.get("collection", ""),
                "module": payload.get("module", ""),
                "commit_sha": payload.get("commit_sha", ""),
                "provenance": payload.get("provenance", ""),
                "payload": payload,
            }

        # source_code (veya source_type eksik — eski chunk'lar)
        return {
            "score":    score,
            "source_type": source_type or "source_code",
            "file":     payload.get("file_path", ""),
            "name":     payload.get("name", ""),
            "type":     payload.get("chunk_type", ""),
            "code":     payload.get("code", ""),
            "lines":    f"{payload.get('start_line', 0)}-{payload.get('end_line', 0)}",
            "language": payload.get("language", ""),
        }
