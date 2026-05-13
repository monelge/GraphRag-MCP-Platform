import pytest

from src.execution.runners.command_runner import CommandRunner


@pytest.mark.asyncio
async def test_command_runner_rejects_non_allowlisted_command() -> None:
    """Allowlist dışı komutların engellendiğini doğrular."""
    runner = CommandRunner()

    result = await runner.run("rm -rf /")

    assert result.exit_code == -1
    assert "Command not allowed" in result.stderr


@pytest.mark.asyncio
async def test_command_runner_timeout_sets_timeout_flag() -> None:
    """Zaman aşımında sonuç nesnesinin doğru işaretlendiğini doğrular."""
    runner = CommandRunner()

    result = await runner.run('/usr/bin/python3 -c "import time; time.sleep(60)"', timeout=1)

    assert result.exit_code == -1
    assert result.timed_out is True
    assert result.success is False
