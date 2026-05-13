import logging
from typing import Optional, List, Dict
from pathlib import Path
from src.execution.runners.command_runner import CommandRunner, ExecutionResult

logger = logging.getLogger(__name__)

class ExecutionProfile:
    def __init__(
        self, 
        name: str, 
        build_cmd: str, 
        test_cmd: str, 
        lint_cmd: str, 
        env_vars: Optional[Dict[str, str]] = None
    ):
        self.name = name
        self.build_cmd = build_cmd
        self.test_cmd = test_cmd
        self.lint_cmd = lint_cmd
        self.env_vars = env_vars or {}

# Önceden tanımlanmış profiller
PROFILES = {
    "dotnet": ExecutionProfile(
        name="dotnet",
        build_cmd="dotnet build",
        test_cmd="dotnet test",
        lint_cmd="dotnet format --verify-no-changes"
    ),
    "python": ExecutionProfile(
        name="python",
        build_cmd="pip install -r requirements.txt",
        test_cmd="pytest",
        lint_cmd="ruff check ."
    ),
    "node": ExecutionProfile(
        name="node",
        build_cmd="npm install && npm run build",
        test_cmd="npm test",
        lint_cmd="npm run lint"
    ),
    "flutter": ExecutionProfile(
        name="flutter",
        build_cmd="flutter pub get",
        test_cmd="flutter test",
        lint_cmd="flutter analyze"
    )
}

class SandboxRuntimeManager:
    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def detect_profile(self, project_path: str) -> ExecutionProfile:
        root = Path(project_path)
        if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
            return PROFILES["dotnet"]
        if (root / "pubspec.yaml").exists():
            return PROFILES["flutter"]
        if (root / "package.json").exists():
            return PROFILES["node"]
        if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
            return PROFILES["python"]
        
        # Varsayılan profil (veya hata)
        return PROFILES["python"] 

    async def run_build(self, project_path: str) -> ExecutionResult:
        profile = self.detect_profile(project_path)
        return await self.runner.run(profile.build_cmd, cwd=project_path, env=profile.env_vars)

    async def run_tests(self, project_path: str) -> ExecutionResult:
        profile = self.detect_profile(project_path)
        return await self.runner.run(profile.test_cmd, cwd=project_path, env=profile.env_vars)

    async def run_lint(self, project_path: str) -> ExecutionResult:
        profile = self.detect_profile(project_path)
        return await self.runner.run(profile.lint_cmd, cwd=project_path, env=profile.env_vars)
