import os
import logging
from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)

VALID_LABELS = {"Module", "Class", "Function", "Method", "Import", "Config"}
VALID_REL_TYPES = {"CONTAINS", "OWNS", "DEPENDS_ON", "CALLS", "IMPLEMENTS", "USES_CONFIG"}


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
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.driver = None
        # Her proje kendi collection adıyla Neo4j'de izole tutulur
        self.collection = collection

    async def connect(self):
        if not self.driver:
            self.driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # Bağlantıyı doğrula
            await self.driver.verify_connectivity()

    async def close(self):
        if self.driver:
            await self.driver.close()
            self.driver = None

    async def execute_query(self, query, parameters=None):
        """Genel amaçlı Cypher sorgusu çalıştırır."""
        if not self.driver:
            await self.connect()
        
        async with self.driver.session() as session:
            result = await session.run(query, parameters)
            return [record async for record in result]

    async def query(self, query, parameters=None):
        """Geriye dönük ve yeni servisler için kısaltma alias'ı."""
        return await self.execute_query(query, parameters)

    async def create_constraints(self):
        """Performans ve veri bütünlüğü için temel Neo4j kısıtlamalarını oluşturur."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:CodeEntity) REQUIRE n.name IS NOT NULL",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:File) REQUIRE n.path IS NOT NULL",
        ]
        # collection bazlı sorgular için composite index — proje izolasyonu
        indexes = [
            "CREATE INDEX idx_module_collection IF NOT EXISTS FOR (n:Module) ON (n.collection)",
            "CREATE INDEX idx_class_collection  IF NOT EXISTS FOR (n:Class)  ON (n.collection)",
            "CREATE INDEX idx_func_collection   IF NOT EXISTS FOR (n:Function) ON (n.collection)",
            "CREATE INDEX idx_module_name_coll  IF NOT EXISTS FOR (n:Module) ON (n.name, n.collection)",
            "CREATE INDEX idx_class_name_coll   IF NOT EXISTS FOR (n:Class)  ON (n.name, n.collection)",
            "CREATE INDEX idx_func_name_coll    IF NOT EXISTS FOR (n:Function) ON (n.name, n.collection)",
        ]
        for cypher in constraints + indexes:
            try:
                await self.execute_query(cypher)
            except Exception as e:
                # Constraint/index zaten varsa ya da desteklenmiyorsa sessizce geç
                logger.debug("Constraint/index oluşturulamadı (görmezden gelindi): %s", e)

    async def upsert_nodes_and_relationships(self, relations: list[dict]):
        """Extractor'dan gelen ilişkileri ve nodeları Neo4j'ye yazar.

        Her node'a collection property eklenir — farklı projeler aynı Neo4j
        instance'ında karışmaz. MERGE anahtarı (name + collection) çiftidir.
        """
        if not self.driver:
            await self.connect()

        coll = self.collection or "default"

        async with self.driver.session() as session:
            for rel in relations:
                source = rel["source"]
                target = rel["target"]
                source_label = _validate_label(source["label"])
                target_label = _validate_label(target["label"])
                rel_type = _validate_rel_type(rel["type"])

                # Tek sorguda ardışık MERGE kullanarak cartesian product uyarısını önle.
                upsert_query = (
                    f"MERGE (s:{source_label} {{name: $s_name, collection: $coll}}) "
                    f"SET s += $s_props "
                    f"MERGE (t:{target_label} {{name: $t_name, collection: $coll}}) "
                    f"SET t += $t_props "
                    f"MERGE (s)-[:{rel_type}]->(t)"
                )

                s_props = {k: v for k, v in source.items() if k not in ["label", "name"]}
                s_props["collection"] = coll
                t_props = {k: v for k, v in target.items() if k not in ["label", "name"]}
                t_props["collection"] = coll

                await session.run(
                    upsert_query,
                    {
                        "s_name": source["name"],
                        "t_name": target["name"],
                        "coll": coll,
                        "s_props": s_props,
                        "t_props": t_props,
                    },
                )
