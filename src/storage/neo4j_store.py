import logging

from neo4j import AsyncGraphDatabase

from src.ontology.builders import build_upsert_query
from src.shared.config import config

logger = logging.getLogger(__name__)
VALID_LABELS = {"Module", "Class", "Function", "Method", "Import", "Config", "Repository", "Package", "File", "Interface", "Endpoint", "Entity", "DTO", "Migration", "UIComponent", "BusinessRule", "Decision", "Owner"}
VALID_REL_TYPES = {"CONTAINS", "OWNS", "DEPENDS_ON", "CALLS", "IMPLEMENTS", "USES_CONFIG", "EXPOSES_ENDPOINT", "MUTATES_ENTITY", "READS_ENTITY", "RELATES_TO_RULE", "AFFECTS_MODULE", "SUPERSEDES_DECISION"}


def _validate_label(label: str) -> str:
    if label not in VALID_LABELS:
        raise ValueError(f"Invalid label: {label}")
    return label


def _validate_rel_type(rel_type: str) -> str:
    if rel_type not in VALID_REL_TYPES:
        raise ValueError(f"Invalid relation type: {rel_type}")
    return rel_type


class Neo4jStore:
    def __init__(self, collection: str = ""):
        self.uri = config.neo4j_uri
        self.user = config.neo4j_user
        self.password = config.neo4j_password
        self.driver = None
        self._default_collection = collection

    async def connect(self, max_retries: int = 10, retry_delay: float = 3.0):
        import asyncio

        if self.driver:
            return
        self.driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                await self.driver.verify_connectivity()
                await self.create_constraints()
                return
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.warning("Neo4j bağlantısı bekleniyor (%s/%s): %s", attempt, max_retries, exc)
                    await asyncio.sleep(retry_delay)
        await self.driver.close()
        self.driver = None
        raise last_exc

    async def close(self):
        if self.driver:
            await self.driver.close()
            self.driver = None

    async def execute_query(self, query, parameters=None):
        if not self.driver:
            await self.connect()
        async with self.driver.session() as session:
            result = await session.run(query, parameters)
            return [record async for record in result]

    async def query(self, query, parameters=None):
        return await self.execute_query(query, parameters)

    async def create_constraints(self):
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:CodeEntity) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:File) REQUIRE n.path IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX idx_module_collection IF NOT EXISTS FOR (n:Module) ON (n.collection)",
            "CREATE INDEX idx_class_collection IF NOT EXISTS FOR (n:Class) ON (n.collection)",
            "CREATE INDEX idx_func_collection IF NOT EXISTS FOR (n:Function) ON (n.collection)",
            "CREATE INDEX idx_module_name_coll IF NOT EXISTS FOR (n:Module) ON (n.name, n.collection)",
            "CREATE INDEX idx_class_name_coll IF NOT EXISTS FOR (n:Class) ON (n.name, n.collection)",
            "CREATE INDEX idx_func_name_coll IF NOT EXISTS FOR (n:Function) ON (n.name, n.collection)",
        ]
        for cypher in constraints + indexes:
            try:
                await self.execute_query(cypher)
            except Exception as exc:
                logger.debug("Constraint/index oluşturulamadı: %s", exc)

    async def upsert_nodes_and_relationships(self, relations: list, collection: str = ""):
        if not self.driver:
            await self.connect()
        coll = collection or self._default_collection or "default"
        async with self.driver.session() as session:
            for rel in relations:
                source = rel["source"]
                target = rel["target"]
                source_label = _validate_label(source["label"])
                target_label = _validate_label(target["label"])
                rel_type = _validate_rel_type(rel["type"])
                upsert_query = build_upsert_query(source_label, target_label, rel_type)
                s_props = {k: v for k, v in source.items() if k not in ["label", "name"]}
                s_props["collection"] = coll
                t_props = {k: v for k, v in target.items() if k not in ["label", "name"]}
                t_props["collection"] = coll
                await session.run(upsert_query, {"s_name": source["name"], "t_name": target["name"], "coll": coll, "s_props": s_props, "t_props": t_props})

    # --- Knowledge Plane V2 Metodları ---

    async def run_pagerank_analysis(self, collection: str) -> dict[str, float]:
        """
        Neo4j üzerinde Degree Centrality bazlı PageRank simülasyonu yapar ve skorları kalıcı olarak yazar.
        GDS eklentisi yoksa APOC veya ham Cypher ile 'mimari önem' skorlarını hesaplar ve 'pagerank' property'sine yazar.
        """
        # 1. Tüm node'lar için degree hesapla ve max_degree'yi bul
        query_calc = """
        MATCH (n {collection: $coll})
        OPTIONAL MATCH (n)-[r]-()
        WITH n, count(r) AS degree
        RETURN n.name AS name, degree
        """
        records = await self.execute_query(query_calc, {"coll": collection})
        if not records:
            return {}
        
        degrees = {r["name"]: r["degree"] for r in records if r["name"]}
        max_deg = max(degrees.values()) or 1
        
        # 2. Skorları DB'ye geri yaz (Batch Update)
        # Verimlilik için tek bir sorgu ile tüm koleksiyonu güncelleyelim
        query_update = """
        UNWIND $data AS item
        MATCH (n {name: item.name, collection: $coll})
        SET n.pagerank = item.score
        """
        
        update_data = [
            {"name": name, "score": float(deg) / max_deg}
            for name, deg in degrees.items()
        ]
        
        # asyncpg benzeri bir batching gerekebilir ama Neo4j driver UNWIND ile bunu iyi yönetir
        await self.execute_query(query_update, {"data": update_data, "coll": collection})
        
        logger.info("PageRank analizi tamamlandı ve %s node güncellendi (coll: %s)", len(update_data), collection)
        return {item["name"]: item["score"] for item in update_data}

    async def detect_communities(self, collection: str) -> list[dict]:
        """
        Mantıksal toplulukları (Communities) tespit eder.
        Dosya yapısından bağımsız olarak birbirini çağıran node gruplarını döndürür.
        """
        # APOC sürümü (bağımlılık zinciri üzerinden kümeleme simülasyonu)
        # V2 Optimizasyonu: Bellek tüketimi için 1-hop derinliğe indirildi.
        query = """
        MATCH (n {collection: $coll})
        OPTIONAL MATCH (n)-[:CALLS|DEPENDS_ON*1..1]-(m {collection: $coll})
        WITH n, collect(DISTINCT m.name) AS neighbors
        WHERE size(neighbors) > 1
        RETURN n.name AS center, neighbors AS community_members, size(neighbors) AS strength
        ORDER BY strength DESC
        LIMIT 10
        """
        return await self.execute_query(query, {"coll": collection})

    async def get_repo_skeleton(self, collection: str) -> list[dict]:
        """
        Tüm projenin imza seviyesindeki iskeletini (Module -> Class -> Function) döner.
        Repo Map üretimi için kullanılır.
        """
        query = """
        MATCH (m:Module {collection: $coll})
        OPTIONAL MATCH (m)-[:CONTAINS]->(c:Class)
        OPTIONAL MATCH (c)-[:OWNS]->(f:Function)
        RETURN m.name AS module, collect(DISTINCT {class: c.name, func: f.name}) AS structure
        """
        return await self.execute_query(query, {"coll": collection})
