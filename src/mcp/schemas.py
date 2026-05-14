"""MCP tool giriş şemaları için hafif veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchCodeInput:
    collection: str
    query: str
    top_k: int = 0


@dataclass
class CreateTaskInput:
    title: str
    description: str
    collection: str
    steps: List[str] = field(default_factory=list)


@dataclass
class ResumeTaskInput:
    task_id: str


@dataclass
class IndexProjectInput:
    project_path: str
    collection: str = ""
    batch_size: int = 32


@dataclass
class IncrementalIndexProjectInput:
    project_path: str
    changed_files: Optional[List[str]] = None
    batch_size: int = 32


@dataclass
class StoreMemoryInput:
    title: str
    content: str
    memory_type: str = "general"
    collection: str = ""


@dataclass
class RecallMemoryInput:
    query: str
    collection: str = ""
    top_k: int = 5


@dataclass
class RunVerificationPlanInput:
    project_path: str
    run_build: bool = True
    run_tests: bool = True
    run_lint: bool = False
