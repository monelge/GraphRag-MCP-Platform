"""Task checkpoint kayıtları için PostgreSQL tabanlı depo."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.agent.tasks.task_models import Task
from src.storage.postgres_store import PostgresStore


@dataclass
class TaskCheckpoint:
    checkpoint_id: str
    task_id: str
    current_node: str
    step_index: int
    task_context: Dict[str, Any] = field(default_factory=dict)
    file_patches: List[dict] = field(default_factory=list)
    command_results: List[dict] = field(default_factory=list)
    created_at: float = 0.0


class CheckpointStore:
    """Checkpoint kayıtlarını task güncellemeleriyle aynı transaction'da saklar."""

    def __init__(self, postgres_store: PostgresStore):
        self.pg = postgres_store

    async def save(
        self,
        task: Task,
        current_node: str,
        step_index: int,
        file_patches: Optional[List[dict]] = None,
        command_results: Optional[List[dict]] = None,
        conn=None,
    ) -> TaskCheckpoint:
        checkpoint = TaskCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            task_id=task.task_id,
            current_node=current_node,
            step_index=step_index,
            task_context=dict(task.context),
            file_patches=file_patches or [],
            command_results=command_results or [],
            created_at=time.time(),
        )
        if not self.pg.available:
            return checkpoint
        if conn is not None:
            await self._insert(conn, checkpoint)
            return checkpoint
        async with self.pg._pool.acquire() as acquired:
            async with acquired.transaction():
                await self._insert(acquired, checkpoint)
        return checkpoint

    async def _insert(self, conn, checkpoint: TaskCheckpoint) -> None:
        await conn.execute(
            """
            INSERT INTO task_checkpoints
                (checkpoint_id, task_id, current_node, step_index, task_context, file_patches, command_results, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, TO_TIMESTAMP($8))
            """,
            checkpoint.checkpoint_id,
            checkpoint.task_id,
            checkpoint.current_node,
            checkpoint.step_index,
            json.dumps(checkpoint.task_context, ensure_ascii=False),
            json.dumps(checkpoint.file_patches, ensure_ascii=False),
            json.dumps(checkpoint.command_results, ensure_ascii=False),
            checkpoint.created_at,
        )

    async def get_latest(self, task_id: str) -> Optional[TaskCheckpoint]:
        if not self.pg.available:
            return None
        async with self.pg._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM task_checkpoints WHERE task_id = $1 ORDER BY created_at DESC LIMIT 1",
                task_id,
            )
        return self._from_row(row) if row else None

    async def list_checkpoints(self, task_id: str) -> List[TaskCheckpoint]:
        if not self.pg.available:
            return []
        async with self.pg._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM task_checkpoints WHERE task_id = $1 ORDER BY created_at DESC",
                task_id,
            )
        return [self._from_row(row) for row in rows]

    async def delete_task_checkpoints(self, task_id: str) -> None:
        if not self.pg.available:
            return
        async with self.pg._pool.acquire() as conn:
            await conn.execute("DELETE FROM task_checkpoints WHERE task_id = $1", task_id)

    @staticmethod
    def _from_row(row) -> TaskCheckpoint:
        return TaskCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            task_id=row["task_id"],
            current_node=row["current_node"],
            step_index=row["step_index"],
            task_context=row["task_context"] if isinstance(row["task_context"], dict) else json.loads(row["task_context"] or "{}"),
            file_patches=row["file_patches"] if isinstance(row["file_patches"], list) else json.loads(row["file_patches"] or "[]"),
            command_results=row["command_results"] if isinstance(row["command_results"], list) else json.loads(row["command_results"] or "[]"),
            created_at=row["created_at"].timestamp() if hasattr(row["created_at"], "timestamp") else float(row["created_at"]),
        )
