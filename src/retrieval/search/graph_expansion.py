"""
Graph Expansion — Neo4j üzerinden dependency chain traversal.

Amaç:
  Vektör araması bir entrypoint bulduğunda (AuthController, UserService vb.),
  Neo4j'deki CONTAINS / OWNS / CALLS ilişkilerini izleyerek
  ilgili tüm bağımlılık zincirini tespit eder.

Çift Mod:
  1. Enrich (varsayılan): retrieval sonrası graph_centrality ekle
  2. Augment (graph-first candidate augmentation):
       code_relation ve broad_summary sorguları için
       entrypoint zincirinden Qdrant'ta targeted retrieval çalıştırır.
       Normal retrieval'ın YERİNE geçmez; ek aday sağlar.

Neden augment modeli?
  Vektör araması semantik benzerlik üzerinden çalışır —
  "login flow" sorgusunda CookieMiddleware'i bulmak için
  anlamsal benzerlik yetersiz kalır, ancak graf zinciri
  AuthController → JwtService → CookieMiddleware'i doğrudan gösterir.
  Augment modeli normal retrieval'ı kaldırmaz; candidate set'i zenginleştirir.

Geri dönüş değeri:
  İlgili node isimleri listesi (string) — bu isimler
  HybridSearcher tarafından Qdrant name filtresi olarak kullanılabilir.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Tek bir entrypoint'ten kaç hop ilerleneceği — derin zinciri kesmek için
MAX_HOPS = 3
# Tek sorguda döndürülecek maksimum bağımlı node sayısı
MAX_NODES = 15

# Graph-first augmentation hangi query tiplerinde aktif
_GRAPH_FIRST_TYPES = {"code_relation", "broad_summary", "architecture_analysis"}


class GraphExpander:
    """
    Neo4jStore üzerinden dependency chain expansion sağlar.
    neo4j_store: mevcut Neo4jStore instance'ı (bağlantı önceden açılmış olmalı).
    """

    def __init__(self, neo4j_store):
        self._neo4j = neo4j_store

    async def expand(self, entrypoints: list[str], collection: str = "") -> list[str]:
        """
        Verilen entrypoint adlarından başlayarak bağımlılık zincirini takip eder.
        Zincirdeki tüm node isimlerini (tekrarsız) döner.

        entrypoints: search_code'dan gelen top chunk name'leri
        collection: proje izolasyonu — yalnızca bu collection'a ait node'lar getirilir
        """
        if not entrypoints:
            return []

        all_nodes: set[str] = set(entrypoints)
        coll_filter = "AND start.collection = $coll " if collection else ""
        dep_filter  = "AND dep.collection = $coll "   if collection else ""

        try:
            cypher = f"""
            MATCH (start)
            WHERE start.name IN $names {coll_filter}
            CALL apoc.path.subgraphNodes(start, {{
                relationshipFilter: 'CONTAINS>|OWNS>|CALLS>',
                maxLevel: $max_hops
            }})
            YIELD node
            WHERE node.collection = $coll OR $coll = ''
            RETURN DISTINCT node.name AS name
            LIMIT $max_nodes
            """
            records = await self._neo4j.execute_query(
                cypher,
                parameters={
                    "names": entrypoints,
                    "max_hops": MAX_HOPS,
                    "max_nodes": MAX_NODES,
                    "coll": collection,
                },
            )
            for record in records:
                name = record.get("name") if isinstance(record, dict) else record["name"]
                if name:
                    all_nodes.add(name)

        except Exception as e:
            logger.debug("GraphExpansion APOC fallback: %s", e)
            try:
                cypher_simple = f"""
                MATCH (start)-[:CONTAINS|OWNS|CALLS]->(dep)
                WHERE start.name IN $names {coll_filter}{dep_filter}
                RETURN DISTINCT dep.name AS name
                LIMIT $max_nodes
                """
                records = await self._neo4j.execute_query(
                    cypher_simple,
                    parameters={"names": entrypoints, "max_nodes": MAX_NODES, "coll": collection},
                )
                for record in records:
                    name = record.get("name") if isinstance(record, dict) else record["name"]
                    if name:
                        all_nodes.add(name)
            except Exception:
                pass

        return list(all_nodes)

    async def augment_candidates(
        self,
        query: str,
        collection: str,
        normal_candidates: list[dict],
        query_type: str,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Graph-first candidate augmentation.

        Normal retrieval sonuçlarındaki entrypoint'lerden dependency zinciri
        çıkarır, Qdrant'ta name-based targeted retrieval yapar ve sonuçları
        normal_candidates ile birleştirir.

        Bu metod yalnızca code_relation / broad_summary sorguları için çağrılmalıdır.
        Diğer query tiplerinde normal_candidates aynen döner.

        Önemli: Normal retrieval'ı kaldırmaz; ek aday ekler.
        """
        if query_type not in _GRAPH_FIRST_TYPES or not normal_candidates:
            return normal_candidates

        entrypoints = [c.get("name", "") for c in normal_candidates[:5] if c.get("name")]
        if not entrypoints:
            return normal_candidates

        try:
            graph_nodes = await self.expand(entrypoints, collection=collection)
            # Graph'tan gelen node'ları Qdrant'ta ara — name filtresi ile
            if len(graph_nodes) > len(entrypoints):  # Yeni node'lar bulunduysa
                from src.retrieval.search.hybrid_search import HybridSearcher
                from qdrant_client.models import Filter, FieldCondition, MatchAny
                graph_filter = Filter(must=[
                    FieldCondition(key="name", match=MatchAny(any=graph_nodes[:20]))
                ])
                searcher = HybridSearcher(collection=collection)
                graph_candidates = await searcher.search(
                    query, top_k=top_k, query_filter=graph_filter
                )
                # Graph candidate'leri işaretle ve normal sonuçlara ekle
                for c in graph_candidates:
                    c["_from_graph"] = True

                # Birleştir — deduplicate (aynı name/file → yüksek skoru koru)
                seen: dict[str, dict] = {}
                for c in normal_candidates + graph_candidates:
                    key = f"{c.get('file','')}:{c.get('name','')}"
                    existing = seen.get(key)
                    if not existing or float(c.get("score", 0)) > float(existing.get("score", 0)):
                        seen[key] = c
                return sorted(seen.values(), key=lambda x: float(x.get("score", 0)), reverse=True)

        except Exception as exc:
            logger.debug("Graph augmentation başarısız, normal candidates kullanılıyor: %s", exc)

        return normal_candidates

    async def get_centrality(self, node_names: list[str]) -> dict[str, float]:
        """
        Verilen node'ların graf merkeziliğini (degree centrality) döner.
        final_score hesabında graph_centrality bileşeni için kullanılır.
        Normalize: max_degree → 1.0
        """
        if not node_names:
            return {}

        try:
            cypher = """
            MATCH (n)
            WHERE n.name IN $names
            OPTIONAL MATCH (n)-[r]-()
            RETURN n.name AS name, count(r) AS degree
            """
            records = await self._neo4j.execute_query(
                cypher, parameters={"names": node_names}
            )
            degrees: dict[str, int] = {}
            for record in records:
                name = record.get("name") if isinstance(record, dict) else record["name"]
                degree = record.get("degree") if isinstance(record, dict) else record["degree"]
                if name is not None:
                    degrees[name] = int(degree or 0)

            if not degrees:
                return {}

            max_degree = max(degrees.values()) or 1
            return {name: deg / max_degree for name, deg in degrees.items()}

        except Exception:
            return {}
