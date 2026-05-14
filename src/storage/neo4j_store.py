import logging

from neo4j import AsyncGraphDatabase

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
                await session.run(upsert_query, {"s_name": source["name"], "t_name": target["name"], "coll": coll, "s_props": s_props, "t_props": t_props})
