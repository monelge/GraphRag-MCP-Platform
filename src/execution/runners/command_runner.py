import asyncio
import logging
import shlex
import shutil
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = {
    "/usr/bin/python3",
    "/usr/local/bin/python3",  # macOS Homebrew / Docker base image alternatif yolu
    "/usr/bin/node",
    "/usr/local/bin/node",     # macOS Homebrew / Docker base image alternatif yolu
    "/bin/bash",
    "/usr/bin/bash",
}
_BLOCKED_BASH_FLAGS = {"-c", "-lc"}

@dataclass
class ExecutionResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

class CommandRunner:
    """
    Güvenli komut çalıştırma motoru.
    Timeouts, logging ve temel izolasyon kurallarını uygular.
    """

    def __init__(self, default_timeout: int = 300):
        self.default_timeout = default_timeout

    def _resolve_executable(self, executable: str) -> str:
        resolved = executable if executable.startswith("/") else shutil.which(executable)
        if not resolved:
            raise ValueError(f"Command not found: {executable}")

        if resolved not in ALLOWED_COMMANDS:
            raise ValueError(f"Command not allowed: {resolved}")

        return resolved

    async def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        t0 = time.monotonic()
        effective_timeout = timeout or self.default_timeout

        logger.info("Komut çalıştırılıyor: %s (cwd=%s)", command, cwd)

        try:
            cmd_parts = shlex.split(command)
            if not cmd_parts:
                raise ValueError("Command is empty")

            executable = self._resolve_executable(cmd_parts[0])
            if executable == "/bin/bash" and any(flag in _BLOCKED_BASH_FLAGS for flag in cmd_parts[1:2]):
                raise ValueError("Inline bash commands are not allowed")

            cmd_parts[0] = executable
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env or None,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
                exit_code = process.returncode
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                exit_code = -1
                timed_out = True
                logger.warning("Komut zaman aşımına uğradı: %s", command)

            duration = time.monotonic() - t0
            return ExecutionResult(
                command=command,
                exit_code=exit_code if exit_code is not None else -1,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                duration=duration,
                timed_out=timed_out,
            )

        except Exception as e:
            logger.exception("Komut yürütme hatası: %s", command)
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=time.monotonic() - t0,
            )
