from __future__ import annotations

"""Komut allowlist ve bash güvenlik bayraklarını merkezi yöneten politika modülü."""

import os

_BASE_ALLOWED_EXECUTABLES = frozenset(
    {
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/node",
        "/usr/local/bin/node",
        "/bin/bash",
        "/usr/bin/bash",
    }
)
_EXTRA_ALLOWED_EXECUTABLES = frozenset(
    item.strip() for item in os.getenv("TOOL_POLICY_EXTRA_ALLOWED", "").split(";") if item.strip()
)
ALLOWED_EXECUTABLES: frozenset[str] = frozenset(set(_BASE_ALLOWED_EXECUTABLES) | set(_EXTRA_ALLOWED_EXECUTABLES))
BLOCKED_BASH_FLAGS: frozenset[str] = frozenset({"-c", "-lc"})


def is_allowed(executable_path: str) -> bool:
    """Executable yolunun allowlist içinde olup olmadığını döndürür."""
    return executable_path in ALLOWED_EXECUTABLES


def is_blocked_bash_flag(flag: str) -> bool:
    """Bash flag'inin engelli inline-exec bayraklarından biri olup olmadığını döndürür."""
    return flag in BLOCKED_BASH_FLAGS
