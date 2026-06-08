"""
Workspace Manager — git worktree tabanlı ephemeral çalışma alanı yönetimi.

Her görev için:
  - /var/lib/graphrag/workspaces/task_{id}  dizini açılır
  - Görev bitiminde worktree kaldırılır
  - snapshot_{task_id} etiketi alınır
  - GC: SNAPSHOT_RETENTION_HOURS + MAX_SNAPSHOTS_PER_PROJECT limiti
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

WORKSPACE_BASE: Path = Path(os.getenv("WORKSPACE_BASE_PATH", "/var/lib/graphrag/workspaces"))
SNAPSHOT_RETENTION_H: int = int(os.getenv("SNAPSHOT_RETENTION_HOURS", "24"))
MAX_SNAPSHOTS: int = int(os.getenv("MAX_SNAPSHOTS_PER_PROJECT", "20"))


@dataclass
class WorkspaceInfo:
    task_id:     str
    path:        Path
    project_path: Path
    snapshot_ref: Optional[str] = None   # git tag/branch adı
    created_at:  float = 0.0


class WorkspaceManager:
    """git worktree ile izole çalışma alanları oluşturur ve temizler."""

    def __init__(self) -> None:
        WORKSPACE_BASE.mkdir(parents=True, exist_ok=True)

    # ── Workspace oluşturma ────────────────────────────────────────────────

    async def create(self, task_id: str, project_path: str) -> WorkspaceInfo:
        proj = Path(project_path)
        ws_path = WORKSPACE_BASE / f"task_{task_id}"

        if not (proj / ".git").exists():
            # Git repo değil — dizini kopyala
            logger.warning("Proje git repo değil, kopyalanıyor: %s", project_path)
            await asyncio.to_thread(shutil.copytree, str(proj), str(ws_path), dirs_exist_ok=True)
            info = WorkspaceInfo(
                task_id=task_id, path=ws_path,
                project_path=proj, created_at=time.time(),
            )
            return info

        # Snapshot al
        snap_ref = await self._take_snapshot(proj, task_id)

        # git worktree add
        branch = f"agent/task-{task_id}"
        try:
            await self._git(proj, ["worktree", "add", "-b", branch, str(ws_path), "HEAD"])
            logger.info("Worktree oluşturuldu: %s (branch=%s)", ws_path, branch)
        except Exception as exc:
            logger.error("Worktree oluşturulamadı: %s — fallback copy", exc)
            await asyncio.to_thread(shutil.copytree, str(proj), str(ws_path), dirs_exist_ok=True)

        return WorkspaceInfo(
            task_id=task_id, path=ws_path, project_path=proj,
            snapshot_ref=snap_ref, created_at=time.time(),
        )

    async def remove(self, info: WorkspaceInfo) -> None:
        """Worktree'yi kaldırır ve geçici branch'i siler."""
        proj = info.project_path
        try:
            if (proj / ".git").exists():
                await self._git(proj, ["worktree", "remove", "--force", str(info.path)])
                branch = f"agent/task-{info.task_id}"
                await self._git(proj, ["branch", "-D", branch])
            elif info.path.exists():
                await asyncio.to_thread(shutil.rmtree, str(info.path), ignore_errors=True)
            logger.info("Worktree kaldırıldı: %s", info.path)
        except Exception as exc:
            logger.warning("Worktree kaldırılamadı (%s): %s", info.path, exc)
            # Dizini zorla sil
            if info.path.exists():
                await asyncio.to_thread(shutil.rmtree, str(info.path), ignore_errors=True)

    async def merge_to_main(self, info: WorkspaceInfo) -> None:
        """Onaylı değişiklikleri ana repoya merge eder."""
        proj = info.project_path
        if not (proj / ".git").exists():
            # Git yok — dosyaları üzerine kopyala
            await asyncio.to_thread(
                shutil.copytree, str(info.path), str(proj), dirs_exist_ok=True
            )
            return
        branch = f"agent/task-{info.task_id}"
        await self._git(proj, ["merge", "--no-ff", branch, "-m", f"agent: task {info.task_id}"])
        logger.info("Merge tamamlandı: %s → main", branch)

    # ── Snapshot ──────────────────────────────────────────────────────────

    async def _take_snapshot(self, project_path: Path, task_id: str) -> Optional[str]:
        tag = f"snapshot_{task_id}"
        try:
            await self._git(project_path, ["tag", tag, "HEAD"])
            logger.debug("Snapshot alındı: %s", tag)
            return tag
        except Exception as exc:
            logger.warning("Snapshot alınamadı: %s", exc)
            return None

    async def rollback_to_snapshot(self, project_path: Path, task_id: str) -> bool:
        tag = f"snapshot_{task_id}"
        try:
            await self._git(Path(project_path), ["reset", "--hard", tag])
            logger.info("Rollback: %s", tag)
            return True
        except Exception as exc:
            logger.error("Rollback başarısız (%s): %s", tag, exc)
            return False

    # ── GC / Temizlik ─────────────────────────────────────────────────────

    async def prune_stale_workspaces(self, active_task_ids: set[str] | None = None) -> int:
        """
        Stale workspace'leri temizler.
        active_task_ids None ise sadece yaş limitine bakılır.
        Döner: temizlenen workspace sayısı.
        """
        removed = 0
        cutoff = time.time() - SNAPSHOT_RETENTION_H * 3600

        for ws_dir in WORKSPACE_BASE.iterdir():
            if not ws_dir.is_dir():
                continue
            name = ws_dir.name
            if not name.startswith("task_"):
                continue

            task_id = name[len("task_"):]
            stat = ws_dir.stat()
            age_ok = stat.st_mtime < cutoff
            inactive = active_task_ids is not None and task_id not in active_task_ids

            if age_ok or inactive:
                try:
                    await asyncio.to_thread(shutil.rmtree, str(ws_dir), ignore_errors=True)
                    removed += 1
                    logger.info("GC: stale workspace silindi: %s", ws_dir)
                except Exception as exc:
                    logger.warning("GC workspace silinemedi (%s): %s", ws_dir, exc)

        return removed

    async def prune_snapshots(self, project_path: str) -> int:
        """
        Proje başına MAX_SNAPSHOTS_PER_PROJECT limitini uygular.
        En eski snapshot'lar silinir.
        """
        proj = Path(project_path)
        if not (proj / ".git").exists():
            return 0

        try:
            result = await self._git_output(proj, ["tag", "--list", "snapshot_*", "--sort=creatordate"])
            tags = [t for t in result.strip().splitlines() if t]
            excess = len(tags) - MAX_SNAPSHOTS
            if excess <= 0:
                return 0
            to_delete = tags[:excess]
            for tag in to_delete:
                try:
                    await self._git(proj, ["tag", "-d", tag])
                    logger.debug("Snapshot tag silindi: %s", tag)
                except Exception:
                    pass
            logger.info("Snapshot GC: %d tag silindi (proje=%s)", len(to_delete), proj.name)
            return len(to_delete)
        except Exception as exc:
            logger.warning("Snapshot GC hatası: %s", exc)
            return 0

    # ── Git yardımcıları ──────────────────────────────────────────────────

    @staticmethod
    async def _git(cwd: Path, args: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (rc={proc.returncode}): {stderr.decode().strip()}"
            )

    @staticmethod
    async def _git_output(cwd: Path, args: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode().strip()}")
        return stdout.decode()


# Singleton
_wm: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    global _wm
    if _wm is None:
        _wm = WorkspaceManager()
    return _wm
