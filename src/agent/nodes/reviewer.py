"""Patch etkisini değerlendirip approval gereksinimini belirleyen node."""

from __future__ import annotations

from src.agent.nodes.base import BaseNode, NodeResult
from src.agent.tasks.task_models import TaskStatus


class ReviewerNode(BaseNode):
    name = "reviewer"

    async def run(self, task, ctx) -> NodeResult:
        file_patches = task.context.get("file_patches") or []
        changed_paths = [patch.get("path", "virtual") for patch in file_patches]
        impact = await ctx.impact_analyzer.analyze(task.collection or "default", changed_paths)
        scores = [data.get("score", 0.0) for data in impact.get("files", {}).values()]
        risk_score = max(scores) / 10.0 if scores else 0.0
        if risk_score > 0.7:
            task.status = TaskStatus.WAITING_APPROVAL
            next_node = None
        else:
            next_node = "summarizer"
        return NodeResult(
            success=True,
            output="Risk değerlendirmesi tamamlandı.",
            next_node=next_node,
            context_updates={"risk_score": risk_score, "impact_analysis": impact},
        )
