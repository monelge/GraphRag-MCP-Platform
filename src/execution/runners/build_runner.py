from __future__ import annotations

"""Proje tipini algılayıp build adımlarını güvenli şekilde çalıştıran yardımcı."""

from src.execution.runners.command_runner import CommandRunner, ExecutionResult
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager


class BuildRunner:
    """Build komutlarını profile göre adım adım yürüten sarmalayıcı."""

    def __init__(self, runtime_manager: SandboxRuntimeManager | None = None):
        self.runtime_manager = runtime_manager or SandboxRuntimeManager(CommandRunner())

    def get_profile_name(self, project_path: str) -> str:
        """Algılanan runtime profilinin adını döndürür."""
        return self.runtime_manager.detect_profile(project_path).name

    async def run(self, project_path: str) -> ExecutionResult:
        """Profile ait build komutunu gerekirse parçalayarak çalıştırır."""
        profile = self.runtime_manager.detect_profile(project_path)
        return await self._run_command_chain(profile.build_cmd, project_path, profile.env_vars)

    async def _run_command_chain(self, command: str, project_path: str, env_vars: dict[str, str]) -> ExecutionResult:
        segments = [segment.strip() for segment in command.split("&&") if segment.strip()]
        final_result: ExecutionResult | None = None
        for segment in segments:
            final_result = await self.runtime_manager.runner.run(segment, cwd=project_path, env=env_vars)
            if not final_result.success:
                return final_result
        return final_result or ExecutionResult(command=command, exit_code=0, stdout="", stderr="", duration=0.0)
