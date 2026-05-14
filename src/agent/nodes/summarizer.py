"""Task sonucunu özetleyip hafızaya yazan kapanış node'u."""

from __future__ import annotations

from src.agent.nodes.base import BaseNode, NodeResult
from src.agent.tasks.task_models import TaskStatus
from src.memory.models.memory_models import MemoryEntry


class SummarizerNode(BaseNode):
    name = "summarizer"

    async def run(self, task, ctx) -> NodeResult:
        summary = (
            f"Görev: {task.title}\n"
            f"Açıklama: {task.description}\n"
            f"Risk: {task.context.get('risk_score', 0.0)}\n"
            f"Doğrulama: {task.context.get('verification_result', {})}"
        )
        entry = MemoryEntry(
            title=f"Task Summary: {task.title}",
            content=summary,
            memory_type="resolved_incident",
            collection=task.collection,
            task_id=task.task_id,
        )
        await ctx.episodic.store_memory(entry, redis_store=ctx.redis)
        task.status = TaskStatus.DONE
        return NodeResult(
            success=True,
            output="Görev özeti kaydedildi.",
            next_node=None,
            context_updates={"summary": summary},
        )
