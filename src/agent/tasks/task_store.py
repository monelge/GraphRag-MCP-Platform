from __future__ import annotations

import json
import logging
from typing import List, Optional

import asyncpg

from src.agent.tasks.task_models import Task, TaskStatus, TaskStep
from src.storage.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


class TaskStore:
    """Task ve step kayıtlarını PostgreSQL üzerinde yöneten depo."""

    def __init__(self, pg_store: PostgresStore):
        self.pg = pg_store

    async def save_task(self, task: Task, conn=None) -> bool:
        if not self.pg.available:
            logger.warning("PostgreSQL kullanılamıyor, task %s kaydedilemiyor", task.task_id)
            return False
        try:
            if conn is not None:
                await self._save_with_conn(conn, task)
                return True
            async with self.pg._pool.acquire() as acquired:
                async with acquired.transaction():
                    await self._save_with_conn(acquired, task)
            return True
        except asyncpg.PostgresError as exc:
            logger.error("Task %s kaydedilirken PostgreSQL hatası: %s", task.task_id, exc)
            return False
        except Exception as exc:
            logger.error("Task %s kaydedilirken beklenmeyen hata: %s", task.task_id, exc)
            return False

    async def _save_with_conn(self, conn, task: Task) -> None:
        await conn.execute(
            """
            INSERT INTO tasks (task_id, title, description, status, collection, context, metadata, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, NOW())
            ON CONFLICT (task_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                collection = EXCLUDED.collection,
                context = EXCLUDED.context,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            task.task_id,
            task.title,
            task.description,
            task.status.value,
            task.collection,
            json.dumps(task.context, ensure_ascii=False),
            json.dumps(task.metadata, ensure_ascii=False),
        )
        for step in task.steps:
            await conn.execute(
                """
                INSERT INTO task_steps (step_id, task_id, description, status, result, started_at, completed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (step_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    result = EXCLUDED.result,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at
                """,
                step.step_id,
                task.task_id,
                step.description,
                step.status.value,
                step.result,
                step.started_at,
                step.completed_at,
            )

    async def get_task(self, task_id: str) -> Optional[Task]:
        if not self.pg.available:
            return None
        try:
            async with self.pg._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
                if not row:
                    return None
                context = row["context"] if isinstance(row["context"], dict) else json.loads(row["context"] or "{}")
                metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
                task = Task(
                    task_id=row["task_id"],
                    title=row["title"],
                    description=row["description"],
                    status=TaskStatus(row["status"]),
                    collection=row["collection"],
                    context=context,
                    metadata=metadata,
                    created_at=row["created_at"].timestamp(),
                    updated_at=row["updated_at"].timestamp(),
                )
                step_rows = await conn.fetch("SELECT * FROM task_steps WHERE task_id = $1 ORDER BY created_at ASC", task_id)
                for item in step_rows:
                    task.steps.append(
                        TaskStep(
                            step_id=item["step_id"],
                            description=item["description"],
                            status=TaskStatus(item["status"]),
                            result=item["result"],
                            started_at=item["started_at"],
                            completed_at=item["completed_at"],
                        )
                    )
                return task
        except Exception as exc:
            logger.error("Task %s yüklenirken hata: %s", task_id, exc)
            return None

    async def list_tasks(self, collection: Optional[str] = None, status: Optional[TaskStatus] = None) -> List[Task]:
        if not self.pg.available:
            return []
        clauses = []
        params = []
        if collection:
            clauses.append(f"collection = ${len(params) + 1}")
            params.append(collection)
        if status:
            clauses.append(f"status = ${len(params) + 1}")
            params.append(status.value)
        where = " AND ".join(clauses) if clauses else "1=1"
        query = f"SELECT task_id FROM tasks WHERE {where} ORDER BY updated_at DESC"
        async with self.pg._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        tasks = []
        for row in rows:
            task = await self.get_task(row["task_id"])
            if task:
                tasks.append(task)
        return tasks
