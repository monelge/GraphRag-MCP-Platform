from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


_REGISTRY_PATH = Path(os.getenv("PROJECT_REGISTRY_PATH", "/app/data/project_registry.json"))


@dataclass
class ProjectProfile:
    project_name: str
    collection: str
    project_path: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    module_roots: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    summary: str = ""
    indexed_at: float = 0.0


class ProjectRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or _REGISTRY_PATH

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=True, indent=2))

    def upsert(self, profile: ProjectProfile) -> None:
        data = self._load()
        payload = asdict(profile)
        payload["indexed_at"] = profile.indexed_at or time.time()
        data[profile.collection] = payload
        self._save(data)

    def list_profiles(self) -> list[ProjectProfile]:
        data = self._load()
        return [ProjectProfile(**item) for item in data.values()]

    def get(self, collection: str) -> ProjectProfile | None:
        data = self._load()
        raw = data.get(collection)
        return ProjectProfile(**raw) if raw else None
