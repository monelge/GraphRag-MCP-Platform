import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class EvalCase:
    question: str
    expected_files: List[str] = field(default_factory=list)
    expected_entities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class DatasetManager:
    """
    Değerlendirme veri setlerini yönetir.
    """
    def __init__(self, storage_path: str = "data/evals/datasets"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def save_dataset(self, name: str, cases: List[EvalCase]):
        path = os.path.join(self.storage_path, f"{name}.json")
        data = [
            {
                "question": c.question,
                "expected_files": c.expected_files,
                "expected_entities": c.expected_entities,
                "tags": c.tags,
                "metadata": c.metadata
            } for c in cases
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_dataset(self, name: str) -> List[EvalCase]:
        path = os.path.join(self.storage_path, f"{name}.json")
        if not os.path.exists(path):
            return []
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        return [
            EvalCase(
                question=d["question"],
                expected_files=d.get("expected_files", []),
                expected_entities=d.get("expected_entities", []),
                tags=d.get("tags", []),
                metadata=d.get("metadata", {})
            ) for d in data
        ]

    def list_datasets(self) -> List[str]:
        return [f.replace(".json", "") for f in os.listdir(self.storage_path) if f.endswith(".json")]
