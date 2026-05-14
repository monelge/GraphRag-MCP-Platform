import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EvalCase:
    question: str
    expected_files: List[str] = field(default_factory=list)
    expected_entities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DatasetManager:
    """Değerlendirme veri setlerini yönetir."""

    def __init__(self, storage_path: str = "src/control/evals/datasets"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def save_dataset(self, name: str, cases: List[EvalCase]):
        path = os.path.join(self.storage_path, f"{name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([case.__dict__ for case in cases], handle, indent=2, ensure_ascii=False)

    def load_dataset(self, name: str) -> List[EvalCase]:
        path = os.path.join(self.storage_path, f"{name}.json")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        normalized = []
        for item in data:
            question = item.get("question", item.get("query", ""))
            normalized.append(
                EvalCase(
                    question=question,
                    expected_files=item.get("expected_files", []),
                    expected_entities=item.get("expected_entities", []),
                    tags=item.get("tags", []),
                    metadata=item.get("metadata", {}),
                )
            )
        return normalized

    def list_datasets(self) -> List[str]:
        return [name.replace(".json", "") for name in os.listdir(self.storage_path) if name.endswith(".json")]
