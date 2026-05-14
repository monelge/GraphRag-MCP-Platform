"""Dosyaya yazmadan unified diff üreten editor node."""

from __future__ import annotations

from src.agent.nodes.base import BaseNode, NodeResult


class EditorNode(BaseNode):
    name = "editor"

    async def run(self, task, ctx) -> NodeResult:
        explanation = task.context.get("explanation", "")
        retrieved = task.context.get("retrieved_context", {})
        patch_text = (
            "--- a/virtual\n"
            "+++ b/virtual\n"
            "@@ -0,0 +1,4 @@\n"
            "+# LLM patch taslağı\n"
            f"+# Step: {retrieved.get('step', task.title)}\n"
            f"+# Reason: {explanation[:200].replace(chr(10), ' ')}\n"
        )
        try:
            response = await ctx.model_gateway.chat_completion(
                task="explain",
                messages=[
                    {"role": "system", "content": "Yalnızca unified diff üret. Dosyaya yazma, sadece patch üret."},
                    {"role": "user", "content": explanation[:3000]},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            patch_text = response.choices[0].message.content or patch_text
        except Exception:
            pass
        file_patches = [{"path": "virtual", "diff": patch_text}]
        return NodeResult(
            success=True,
            output="Patch üretildi.",
            next_node="verifier",
            context_updates={"file_patches": file_patches},
            file_patches=file_patches,
        )
