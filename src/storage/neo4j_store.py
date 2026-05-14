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
        # Varsayılan collection yalnızca geriye dönük uyumluluk için tutulur.
        self._default_collection = collection

    async def connect(self, max_retries: int = 10, retry_delay: float = 3.0):
        """
        Neo4j'ye bağlanır. Container henüz hazır değilse max_retries kez dener.
        Neden retry? Docker Compose'da neo4j container'ı graph-mcp'den geç ayağa
        kalkabiliyor; ilk bağlantı denemesi ConnectionRefusedError verebilir.
        """
        import asyncio
        if self.driver:
            return
        self.driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                await self.driver.verify_connectivity()
                await self.create_constraints()
                return
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.warning(
                        f"Neo4j bağlantısı bekleniyor ({attempt}/{max_retries}) — "
                        f"{retry_delay:.0f}s sonra tekrar denenecek. Hata: {exc}"
                    )
                    await asyncio.sleep(retry_delay)
        # Tüm denemeler başarısız
        await self.driver.close()
        self.driver = None
        raise last_exc

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
        """Performans ve veri bütünlüğü için temel Neo4j kısıtlamalarını oluşturur.
        
        NOT: Property existence constraints (IS NOT NULL) sadece Enterprise Edition'da
        çalışır. Community Edition için uniqueness constraints kullanıyoruz.
        """
        # Community Edition'da desteklenen uniqueness constraints
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:CodeEntity) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:File) REQUIRE n.path IS UNIQUE",
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

    async def upsert_nodes_and_relationships(
        self,
        relations: list[dict],
        collection: str = "",
    ):
        """Extractor'dan gelen ilişkileri ve nodeları Neo4j'ye yazar.

        collection parametresi çağrı bazında verilir; böylece store instance'ı
        üzerinde paylaşılan mutable state tutulmaz.
        """
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
