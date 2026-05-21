from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.shared.config import config

logger = logging.getLogger(__name__)


@dataclass
class ProjectProfile:
    project_name: str
    collection: str
    project_path: str
    languages: List[str]
    frameworks: List[str]
    package_managers: List[str]
    module_roots: List[str]
    entrypoints: List[str]
    summary: str
    indexed_at: float


class ProjectRegistry:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or config.project_registry_path)
        self._profiles: Dict[str, ProjectProfile] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for coll, profile_data in data.items():
                    self._profiles[coll] = ProjectProfile(**profile_data)
        except Exception as exc:
            logger.error("ProjectRegistry yüklenemedi: %s", exc)

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {coll: asdict(p) for coll, p in self._profiles.items()}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("ProjectRegistry kaydedilemedi: %s", exc)

    def upsert(self, profile: ProjectProfile):
        self._profiles[profile.collection] = profile
        self._save()

    def get_profile(self, collection: str) -> Optional[ProjectProfile]:
        return self._profiles.get(collection)

    def list_profiles(self) -> List[ProjectProfile]:
        return list(self._profiles.values())
