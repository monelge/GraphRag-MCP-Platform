from __future__ import annotations

"""Proje tipine göre test komutlarını filtre desteğiyle çalıştıran yardımcı."""

from src.execution.runners.command_runner import CommandRunner, ExecutionResult
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager


class TestRunner:
    """Profile göre test komutunu oluşturup güvenli biçimde yürütür."""

    def __init__(self, runtime_manager: SandboxRuntimeManager | None = None):
        self.runtime_manager = runtime_manager or SandboxRuntimeManager(CommandRunner())

    async def run(self, project_path: str, test_filter: str = "") -> ExecutionResult:
        """Test komutunu profile göre filtreyle genişletip çalıştırır."""
        profile = self.runtime_manager.detect_profile(project_path)
        command = self._extend_test_command(profile.name, profile.test_cmd, test_filter)
        segments = [segment.strip() for segment in command.split("&&") if segment.strip()]
        final_result: ExecutionResult | None = None
        for segment in segments:
            final_result = await self.runtime_manager.runner.run(segment, cwd=project_path, env=profile.env_vars)
            if not final_result.success:
                return final_result
        return final_result or ExecutionResult(command=command, exit_code=0, stdout="", stderr="", duration=0.0)

    @staticmethod
    def _extend_test_command(profile_name: str, base_command: str, test_filter: str) -> str:
        """Profil bazlı test filtre sözdizimini ekler."""
        clean_filter = test_filter.strip()
        if not clean_filter:
            return base_command
        if profile_name == "python":
            return f"{base_command} -k {clean_filter}"
        if profile_name == "dotnet":
            return f"{base_command} --filter {clean_filter}"
        if profile_name == "node":
            return f"{base_command} -- {clean_filter}"
        if profile_name == "flutter":
            return f"{base_command} --plain-name {clean_filter}"
        return f"{base_command} {clean_filter}"
