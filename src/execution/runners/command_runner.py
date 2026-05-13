import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

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

    async def run(
        self, 
        command: str, 
        cwd: Optional[str] = None, 
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None
    ) -> ExecutionResult:
        t0 = time.monotonic()
        effective_timeout = timeout or self.default_timeout
        
        logger.info(f"Komut çalıştırılıyor: {command} (cwd={cwd})")
        
        try:
            # shell=True risklidir ancak komplex pipeline'lar için gerekebilir.
            # V2'de bunu daha kontrollü hale getireceğiz.
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env or None
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
                exit_code = process.returncode
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                exit_code = -1
                timed_out = True
                logger.warning(f"Komut zaman aşımına uğradı: {command}")
                
            duration = time.monotonic() - t0
            
            return ExecutionResult(
                command=command,
                exit_code=exit_code if exit_code is not None else -1,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                duration=duration,
                timed_out=timed_out
            )
            
        except Exception as e:
            logger.exception(f"Komut yürütme hatası: {command}")
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=time.monotonic() - t0
            )
