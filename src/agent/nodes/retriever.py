"""Planlanan adım için ilgili retrieval bağlamını toplayan node."""

from __future__ import annotations

from src.agent.nodes.base import BaseNode, NodeResult


class RetrieverNode(BaseNode):
    name = "retriever"

    async def run(self, task, ctx) -> NodeResult:
        steps = task.context.get("planned_steps") or [task.description]
        step_index = int(task.context.get("current_step_index", 0))
        current_step = steps[min(step_index, len(steps) - 1)]
        memory_hits = await ctx.episodic.search_memory(current_step, collection=task.collection or None, top_k=3)
        code_context = await ctx.retrieval_handler.search_code(current_step, task.collection, top_k=3)
        return NodeResult(
            success=True,
            output="İlgili bağlam toplandı.",
            next_node="explainer",
            context_updates={
                "retrieved_context": {
                    "step": current_step,
                    "memory_hits": memory_hits,
                    "code_context": code_context,
                }
            },
        )
