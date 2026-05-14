"""
Provenance payload — her retrieval ve memory kaydında bulunmalı.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProvenancePayload:
    project: str = ""
    collection: str = ""
    commit_sha: str = ""
    branch: str = ""
    source_path: str = ""
    source_type: str = ""
    indexed_at: float = 0.0
    valid_from: Optional[float] = None
    valid_to: Optional[float] = None
    confidence: float = 1.0
    generated_by: str = ""
