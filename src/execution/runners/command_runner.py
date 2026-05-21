import asyncio
import logging
import shlex
import shutil
import time
import ast
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from src.execution.sandbox.tool_policy import ALLOWED_EXECUTABLES, BLOCKED_BASH_FLAGS

logger = logging.getLogger(__name__)

# Execution Plane V2: Güvenlik Membranı
PATH_BLACKLIST = {".git", ".env", "node_modules", "__pycache__", ".pytest_cache"}
DANGEROUS_KEYWORDS = {"rm -rf /", "mkfs", "dd if=", "shutdown", ":(){ :|:& };:"}

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

    def _pre_flight_check(self, command: str, cwd: Optional[str] = None):
        """Uçuş öncesi güvenlik ve sözdizimi denetimi."""
        cmd_lower = command.lower()
        
        # 1. Kritik anahtar kelime kontrolü
        for kw in DANGEROUS_KEYWORDS:
            if kw in cmd_lower:
                raise ValueError(f"⚠️ Kritik güvenlik ihlali: Yasaklı komut deseni tespit edildi ('{kw}')")

        # 2. Path Sanitization
        if cwd:
            cwd_path = str(cwd)
            if any(blacklisted in cwd_path for blacklisted in PATH_BLACKLIST):
                raise ValueError(f"⚠️ Yasaklı dizin erişimi: {cwd_path} üzerinde komut çalıştırılamaz.")

        # 3. Python Syntax Check (Eğer python komutuysa)
        if "python" in cmd_lower and "-c" in cmd_lower:
            try:
                # -c den sonraki tırnak içindeki kodu bulmaya çalış
                parts = shlex.split(command)
                for i, part in enumerate(parts):
                    if part == "-c" and i + 1 < len(parts):
                        ast.parse(parts[i+1])
                        break
            except SyntaxError as e:
                raise ValueError(f"⚠️ Python Syntax Hatası: Kod çalıştırılmadan reddedildi. Detay: {e}")
            except Exception:
                pass # Parse edilemiyorsa sandbox'a bırak

    def _resolve_executable(self, executable: str) -> str:
        resolved = executable if executable.startswith("/") else shutil.which(executable)
        if not resolved:
            raise ValueError(f"Command not found: {executable}")

        if resolved not in ALLOWED_EXECUTABLES:
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
            # Execution Plane V2: Pre-flight Validations
            self._pre_flight_check(command, cwd)

            cmd_parts = shlex.split(command)
            if not cmd_parts:
                raise ValueError("Command is empty")

            executable = self._resolve_executable(cmd_parts[0])
            if executable in {"/bin/bash", "/usr/bin/bash"} and any(flag in BLOCKED_BASH_FLAGS for flag in cmd_parts[1:2]):
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

        except ValueError as ve:
            # Pre-flight hatalarını ve beklenen validation hatalarını dışarı fırlat
            raise ve
        except Exception as e:
            logger.exception("Komut yürütme hatası: %s", command)
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=time.monotonic() - t0,
            )
