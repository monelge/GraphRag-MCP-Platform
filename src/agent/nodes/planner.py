"""Task açıklamasından yürütülebilir adımlar üreten planner node."""

from __future__ import annotations

import json

from src.agent.nodes.base import BaseNode, NodeResult


class PlannerNode(BaseNode):
    name = "planner"

    async def run(self, task, ctx) -> NodeResult:
        steps = []
        try:
            response = await ctx.model_gateway.chat_completion(
                task="summarize",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Yalnızca JSON array döndür. "
                            "Her eleman kısa bir uygulama adımı olsun."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Başlık: {task.title}\nAçıklama: {task.description}",
                    },
                ],
                temperature=0.1,
                max_tokens=400,
            )
            raw = response.choices[0].message.content or "[]"
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                steps = [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            steps = [line.strip("- ") for line in task.description.splitlines() if line.strip()]
            if not steps:
                steps = [task.description or task.title or "Görevi analiz et"]
        return NodeResult(
            success=True,
            output="Plan üretildi.",
            next_node="retriever",
            context_updates={"planned_steps": steps, "current_step_index": 0},
        )
