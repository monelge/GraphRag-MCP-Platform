"""Patch'leri doğrulama komutlarıyla test eden node."""

from __future__ import annotations

from pathlib import Path

from src.agent.nodes.base import BaseNode, NodeResult


class VerifierNode(BaseNode):
    name = "verifier"

    async def run(self, task, ctx) -> NodeResult:
        retries = int(task.context.get("verification_retry", 0))
        project_path = task.context.get("project_path") or str(Path.cwd())
        result = await ctx.runtime_manager.run_tests(project_path)
        command_results = [
            {
                "command": ctx.runtime_manager.detect_profile(project_path).test_cmd,
                "success": result.success,
                "stdout": (result.stdout or "")[:1500],
                "stderr": (result.stderr or "")[:1500],
            }
        ]
        next_node = "reviewer" if result.success or retries >= 2 else "editor"
        return NodeResult(
            success=result.success,
            output="Doğrulama tamamlandı." if result.success else "Doğrulama başarısız.",
            next_node=next_node,
            context_updates={
                "verification_result": command_results[0],
                "verification_retry": retries + (0 if result.success else 1),
            },
            command_results=command_results,
        )
