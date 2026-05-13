import logging
from pathlib import Path
from typing import List, Dict, Any, Set
from src.storage.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)

class ImpactAnalyzer:
    def __init__(self, neo4j_store: Neo4jStore):
        self.neo4j = neo4j_store

    async def analyze(self, collection: str, file_paths: List[str]) -> Dict[str, Any]:
        """
        Değişen dosya yolları için etki analizi yapar.
        
        Süreç:
        1. Dosyalardaki entity'leri (Function, Class, Module) bul.
        2. Bu entity'leri çağıranları (callers) 3 seviye derinliğe kadar takip et.
        3. Etkilenen dosyaları ve modülleri grupla.
        4. Etki puanı (impact score) hesapla.
        """
        impact_results = {}
        all_affected_files: Set[str] = set()
        
        for path in file_paths:
            # Normalize path (relative to project root if possible)
            # Neo4j'de path tam yol olarak saklanıyor olabilir.
            
            # 1. Adım: Bu dosyaya ait tüm nodeları bul
            entities = await self._get_entities_in_file(collection, path)
            
            # 2. Adım: Callers (Geriye doğru iz sürme)
            callers = await self._trace_callers(collection, [e["name"] for e in entities])
            
            # 3. Adım: Bağımlılıklar (İleriye doğru iz sürme)
            dependencies = await self._trace_dependencies(collection, [e["name"] for e in entities])
            
            impact_results[path] = {
                "entities": entities,
                "callers": callers,
                "dependencies": dependencies,
                "score": self._calculate_impact_score(callers, dependencies)
            }
            
            for c in callers:
                if "file_path" in c:
                    all_affected_files.add(c["file_path"])
        
        return {
            "files": impact_results,
            "total_affected_files": list(all_affected_files),
            "summary": self._generate_summary(impact_results)
        }

    async def _get_entities_in_file(self, collection: str, file_path: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (n {collection: $coll})
        WHERE n.file_path = $path OR (n:Module AND n.name = $path)
        RETURN labels(n) as labels, n.name as name, n.chunk_type as type
        """
        records = await self.neo4j.query(query, {"coll": collection, "path": file_path})
        return [{"name": r["name"], "labels": r["labels"], "type": r.get("type")} for r in records]

    async def _trace_callers(self, collection: str, entity_names: List[str]) -> List[Dict[str, Any]]:
        if not entity_names:
            return []
            
        # 3 seviye derinliğe kadar CALLS veya DEPENDS_ON ilişkilerini tersten takip et
        query = """
        MATCH (target {collection: $coll})
        WHERE target.name IN $names
        MATCH p = (caller {collection: $coll})-[:CALLS|DEPENDS_ON|OWNS*1..3]->(target)
        RETURN 
            caller.name as name, 
            labels(caller) as labels, 
            caller.file_path as file_path,
            length(p) as distance
        ORDER BY distance ASC
        LIMIT 50
        """
        records = await self.neo4j.query(query, {"coll": collection, "names": entity_names})
        
        seen = set()
        unique_callers = []
        for r in records:
            if r["name"] not in seen:
                unique_callers.append(r)
                seen.add(r["name"])
        return unique_callers

    async def _trace_dependencies(self, collection: str, entity_names: List[str]) -> List[Dict[str, Any]]:
        if not entity_names:
            return []
            
        # 2 seviye derinliğe kadar bağımlılıkları takip et
        query = """
        MATCH (source {collection: $coll})
        WHERE source.name IN $names
        MATCH p = (source)-[:CALLS|DEPENDS_ON|OWNS*1..2]->(target {collection: $coll})
        RETURN 
            target.name as name, 
            labels(target) as labels, 
            target.file_path as file_path,
            length(p) as distance
        ORDER BY distance ASC
        LIMIT 30
        """
        records = await self.neo4j.query(query, {"coll": collection, "names": entity_names})
        
        seen = set()
        unique_deps = []
        for r in records:
            if r["name"] not in seen:
                unique_deps.append(r)
                seen.add(r["name"])
        return unique_deps

    def _calculate_impact_score(self, callers: List[Dict], dependencies: List[Dict]) -> float:
        # Basit bir puanlama: 
        # Her caller mesafe ağırlıklı puan (1/distance)
        # Her dependency daha az ağırlık
        score = 0.0
        for c in callers:
            score += 1.0 / (c.get("distance", 1))
        for d in dependencies:
            score += 0.2 / (d.get("distance", 1))
        return round(score, 2)

    def _generate_summary(self, impact_results: Dict[str, Any]) -> str:
        total_score = sum(res["score"] for res in impact_results.values())
        if total_score > 10:
            return "Yüksek Risk: Değişiklik geniş bir alanı etkiliyor."
        elif total_score > 3:
            return "Orta Risk: Belirli modüller ve bağımlılıkları etkileniyor."
        else:
            return "Düşük Risk: Etki alanı kısıtlı görünüyor."
