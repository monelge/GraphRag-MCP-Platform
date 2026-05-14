"""Agent node temel soyutlamaları."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.agent.tasks.task_models import Task

if TYPE_CHECKING:
    from src.handlers.context import AppContext


@dataclass
class NodeResult:
    """Node çalışmasının standart sonucu."""

    success: bool
    output: str
    next_node: Optional[str]
    context_updates: Dict[str, Any] = field(default_factory=dict)
    file_patches: List[dict] = field(default_factory=list)
    command_results: List[dict] = field(default_factory=list)


class BaseNode(ABC):
    """Tüm ajan node'larının uyguladığı sözleşme."""

    name = "base"

    @abstractmethod
    async def run(self, task: Task, ctx: AppContext) -> NodeResult:
        """Node davranışını çalıştırır."""
        raise NotImplementedError
