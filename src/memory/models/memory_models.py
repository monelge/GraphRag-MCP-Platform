"""Memory veri modelleri ve tip eşlemeleri."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

MemoryLayer = Literal["semantic", "episodic", "procedural", "decision"]
MemoryType = Literal[
    "resolved_incident",
    "architecture_decision",
    "known_bug",
    "production_fix",
    "migration_note",
    "auth_edge_case",
]

_MEMORY_TYPE_TO_LAYER = {
    "resolved_incident": "episodic",
    "architecture_decision": "decision",
    "known_bug": "episodic",
    "production_fix": "procedural",
    "migration_note": "procedural",
    "auth_edge_case": "episodic",
    "semantic": "semantic",
    "episodic": "episodic",
    "procedural": "procedural",
    "decision": "decision",
    "general": "episodic",
    "architectural_decision": "decision",
}


@dataclass
class MemoryEntry:
    """Tek bir bellek kaydı — provenance ve task linkage desteği içerir."""

    title: str
    content: str
    memory_type: str = "episodic"
    tags: list[str] = field(default_factory=list)
    collection: str = ""
    module: str = ""
    commit_sha: str = ""
    provenance: str = ""
    valid_from: Optional[float] = None
    valid_to: Optional[float] = None
    status: str = "active"
    task_id: str = ""
    checkpoint_id: str = ""
    step_id: str = ""
    entry_id: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.entry_id:
            self.entry_id = hashlib.sha256(
                f"{self.title}:{self.content[:200]}".encode("utf-8")
            ).hexdigest()[:16]
        if not self.created_at:
            self.created_at = time.time()
        if self.valid_from is None:
            self.valid_from = self.created_at

    @property
    def memory_layer(self) -> str:
        """Eski veya yeni memory_type değerinden layer bilgisini türetir."""
        return _MEMORY_TYPE_TO_LAYER.get(self.memory_type, "episodic")

    @property
    def is_valid(self) -> bool:
        """Kaydın zaman ve status açısından aktif olup olmadığını döner."""
        now = time.time()
        if self.status != "active":
            return False
        if self.valid_to and now > self.valid_to:
            return False
        return True
