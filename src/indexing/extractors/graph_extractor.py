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

        return relations
