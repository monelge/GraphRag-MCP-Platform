from __future__ import annotations

"""Sandbox içinde path bazlı okuma/yazma izinlerini yöneten basit politika sınıfı."""

import os
from pathlib import Path


class MountPolicy:
    """Read-only ve read-write mount kurallarını normalize ederek uygular."""

    def __init__(self, allowed_paths: list[str] | None = None, readonly_paths: list[str] | None = None):
        env_readonly = self._parse_env_paths("MOUNT_READONLY_PATHS", ["/projects"])
        env_allowed = self._parse_env_paths("MOUNT_READWRITE_PATHS", ["/tmp"])
        self.allowed_paths = self._normalize_paths(allowed_paths if allowed_paths is not None else env_allowed)
        self.readonly_paths = self._normalize_paths(readonly_paths if readonly_paths is not None else env_readonly)

    def is_read_allowed(self, path: str) -> bool:
        """Path read-write veya read-only mount altında ise okumaya izin verir."""
        normalized = self._normalize_path(path)
        return self._is_under(normalized, self.allowed_paths + self.readonly_paths)

    def is_write_allowed(self, path: str) -> bool:
        """Yalnızca read-write mount altında kalan path'lere yazıma izin verir."""
        normalized = self._normalize_path(path)
        return self._is_under(normalized, self.allowed_paths)

    @staticmethod
    def _parse_env_paths(name: str, default: list[str]) -> list[str]:
        raw = os.getenv(name)
        if raw is None:
            return list(default)
        return [item for item in raw.split(":") if item]

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        return [MountPolicy._normalize_path(path) for path in paths if path]

    @staticmethod
    def _normalize_path(path: str) -> str:
        return str(Path(path).expanduser().resolve(strict=False))

    @staticmethod
    def _is_under(path: str, roots: list[str]) -> bool:
        for root in roots:
            if path == root or path.startswith(f"{root}{os.sep}"):
                return True
        return False
