"""Toplanan bağlamı değişiklik önerisine dönüştüren node."""

from __future__ import annotations

from src.agent.nodes.base import BaseNode, NodeResult


class ExplainerNode(BaseNode):
    name = "explainer"

    async def run(self, task, ctx) -> NodeResult:
        retrieved = task.context.get("retrieved_context", {})
        step = retrieved.get("step", task.description)
        explanation = f"Adım: {step}\n\nBağlam:\n{retrieved.get('code_context', '')[:1200]}"
        total_tokens = 0
        try:
            response = await ctx.model_gateway.chat_completion(
                task="explain",
                messages=[
                    {"role": "system", "content": "Kod değişiklik yaklaşımını Türkçe ve uygulanabilir şekilde açıkla."},
                    {"role": "user", "content": explanation},
                ],
                temperature=0.1,
                max_tokens=600,
                task_id=task.task_id,
                node_name=self.name,
            )
            total_tokens = response.usage.total_tokens if response.usage else 0
            explanation = response.choices[0].message.content or explanation
        except Exception:
            pass
        return NodeResult(
            success=True,
            output="Değişiklik açıklaması üretildi.",
            next_node="editor",
            context_updates={"explanation": explanation},
            token_usage=total_tokens,
        )
