import hashlib
from pathlib import Path
from typing import List, Dict, Any
from src.indexing.chunkers.chunk_models import CodeChunk

class GraphExtractor:
    """
    AST üzerinden desteklenen temel ilişkileri çıkarır ve Neo4j için hazırlar.

    Şu an CodeChunk modeli yalnızca hiyerarşik bağlam taşıdığı için
    CONTAINS ve OWNS ilişkileri üretilebilir.
    CALLS / IMPORTS / DEPENDS_ON için chunk modelinde ek semantik alanlar gerekir.
    """
    def __init__(self):
        pass

    def extract_relationships(self, chunks: List[CodeChunk]) -> List[Dict[str, Any]]:
        """
        Chunk listesinden zenginleştirilmiş ilişkileri çıkarır.
        (Module -> Class -> Function, CALLS, IMPORTS)
        """
        relations = []
        for chunk in chunks:
            module_path = chunk.file_path
            chunk_node = {
                "label": chunk.chunk_type.capitalize(),
                "name": chunk.name,
                "id": chunk.chunk_id,
                "file_path": chunk.file_path,
                "project": chunk.project,
                "indexed_at": chunk.indexed_at
            }

            # 1. Hiyerarşik: Module -> Chunk
            relations.append({
                "source": {
                    "label": "Module", 
                    "name": module_path, 
                    "path": module_path,
                    "project": chunk.project
                },
                "target": chunk_node,
                "type": "CONTAINS"
            })

            # 2. Hiyerarşik: Class -> Method
            if chunk.parent_class:
                relations.append({
                    "source": {"label": "Class", "name": chunk.parent_class},
                    "target": {"label": "Function", "name": chunk.name, "id": chunk.chunk_id},
                    "type": "OWNS"
                })

            # 3. Bağımlılık: Chunk -> Imports
            # Not: Import'lar genellikle ham metin halindedir; 
            # ileride bunları modül adlarıyla eşleştirebiliriz.
            for imp in chunk.imports:
                relations.append({
                    "source": {"label": "Module", "name": module_path, "path": module_path},
                    "target": {"label": "Import", "name": imp},
                    "type": "DEPENDS_ON"
                })

            # 4. Çağrı: Chunk -> Calls
            for call in chunk.calls:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "Function", "name": call}, 
                    "type": "CALLS"
                })

            # 5. Kalıtım: Chunk -> Bases (Phase 2)
            for base in chunk.bases:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "Class", "name": base},
                    "type": "IMPLEMENTS"
                })

            # 6. Konfigürasyon: Chunk -> Config (Phase 2)
            for cfg in chunk.config_keys:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "Config", "name": cfg},
                    "type": "USES_CONFIG"
                })

            # 7. Endpoint: Chunk -> Endpoint
            for ep in chunk.endpoints:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "Endpoint", "name": ep, "path": chunk.file_path},
                    "type": "EXPOSES_ENDPOINT"
                })

            # 8. DTO node
            if chunk.is_dto:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "DTO", "name": chunk.name, "path": chunk.file_path},
                    "type": "OWNS"
                })

            # 9. Migration node
            if chunk.is_migration:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "Migration", "name": chunk.name or Path(chunk.file_path).name, "path": chunk.file_path},
                    "type": "OWNS"
                })

            # 10. UIComponent node
            if chunk.is_ui_component:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "UIComponent", "name": chunk.name, "path": chunk.file_path},
                    "type": "OWNS"
                })

            # 11. BusinessRule node
            if chunk.is_business_rule:
                relations.append({
                    "source": chunk_node,
                    "target": {"label": "BusinessRule", "name": chunk.name, "path": chunk.file_path},
                    "type": "RELATES_TO_RULE"
                })

            # 12. Entity node + MUTATES/READS edge inference
            if chunk.is_entity:
                entity_node = {"label": "Entity", "name": chunk.name, "path": chunk.file_path}
                relations.append({
                    "source": chunk_node,
                    "target": entity_node,
                    "type": "OWNS"
                })
                # Write vs Read inference from method names
                lower_name = (chunk.name or "").lower()
                if any(kw in lower_name for kw in ("create", "insert", "update", "delete", "save", "remove", "mutate", "modify", "set", "add", "put", "patch")):
                    relations.append({"source": chunk_node, "target": entity_node, "type": "MUTATES_ENTITY"})
                elif any(kw in lower_name for kw in ("get", "find", "list", "search", "read", "fetch", "query", "select", "retrieve", "load")):
                    relations.append({"source": chunk_node, "target": entity_node, "type": "READS_ENTITY"})

        return relations
