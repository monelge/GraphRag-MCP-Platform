from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from src.ontology.schema import NodeType
from src.ontology.summarizers import node_to_summary_text
from src.storage.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)


class ImpactAnalyzer:
    def __init__(self, neo4j_store: Neo4jStore):
        self.neo4j = neo4j_store

    async def analyze(self, collection: str, file_paths: List[str]) -> Dict[str, Any]:
        impact_results = {}
        all_affected_files: Set[str] = set()
        for path in file_paths:
            entities = await self._get_entities_in_file(collection, path)
            callers = await self._trace_callers(collection, [item["name"] for item in entities])
            dependencies = await self._trace_dependencies(collection, [item["name"] for item in entities])
            impact_results[path] = {"entities": entities, "callers": callers, "dependencies": dependencies, "score": self._calculate_impact_score(callers, dependencies)}
            for caller in callers:
                if "file_path" in caller:
                    all_affected_files.add(caller["file_path"])
        return {"files": impact_results, "total_affected_files": list(all_affected_files), "summary": self._generate_summary(impact_results)}

    async def _get_entities_in_file(self, collection: str, file_path: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (n {collection: $coll})
        WHERE n.file_path = $path OR (n:Module AND n.name = $path)
        RETURN labels(n) as labels, n.name as name, n.chunk_type as type
        """
        records = await self.neo4j.query(query, {"coll": collection, "path": file_path})
        return [{"name": row["name"], "labels": row["labels"], "type": row.get("type")} for row in records]

    async def _trace_callers(self, collection: str, entity_names: List[str]) -> List[Dict[str, Any]]:
        if not entity_names:
            return []
        query = """
        MATCH (target {collection: $coll})
        WHERE target.name IN $names
        MATCH p = (caller {collection: $coll})-[:CALLS|DEPENDS_ON|OWNS|AFFECTS_MODULE*1..3]->(target)
        RETURN caller.name as name, labels(caller) as labels, caller.file_path as file_path, length(p) as distance
        ORDER BY distance ASC
        LIMIT 50
        """
        records = await self.neo4j.query(query, {"coll": collection, "names": entity_names})
        seen = set()
        callers = []
        for row in records:
            if row["name"] not in seen:
                callers.append(row)
                seen.add(row["name"])
        return callers

    async def _trace_dependencies(self, collection: str, entity_names: List[str]) -> List[Dict[str, Any]]:
        if not entity_names:
            return []
        query = """
        MATCH (source {collection: $coll})
        WHERE source.name IN $names
        MATCH p = (source)-[:CALLS|DEPENDS_ON|OWNS|USES_CONFIG*1..2]->(target {collection: $coll})
        RETURN target.name as name, labels(target) as labels, target.file_path as file_path, length(p) as distance
        ORDER BY distance ASC
        LIMIT 30
        """
        records = await self.neo4j.query(query, {"coll": collection, "names": entity_names})
        seen = set()
        dependencies = []
        for row in records:
            if row["name"] not in seen:
                dependencies.append(row)
                seen.add(row["name"])
        return dependencies

    def _calculate_impact_score(self, callers: List[Dict], dependencies: List[Dict]) -> float:
        score = 0.0
        for item in callers:
            score += 1.0 / item.get("distance", 1)
        for item in dependencies:
            score += 0.2 / item.get("distance", 1)
        return round(score, 2)

    def _generate_summary(self, impact_results: Dict[str, Any]) -> str:
        total_score = sum(item["score"] for item in impact_results.values())
        if total_score > 10:
            return "Yüksek Risk: Değişiklik geniş bir alanı etkiliyor."
        if total_score > 3:
            return "Orta Risk: Belirli modüller ve bağımlılıkları etkileniyor."
        return "Düşük Risk: Etki alanı kısıtlı görünüyor."
