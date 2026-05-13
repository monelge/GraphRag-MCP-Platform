import json
import logging
from typing import List, Optional
from src.storage.postgres_store import PostgresStore
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep, TaskCheckpoint

logger = logging.getLogger(__name__)

class TaskStore:
    def __init__(self, pg_store: PostgresStore):
        self.pg = pg_store

    async def save_task(self, task: Task):
        if not self.pg.available:
            return
        
        async with self.pg._pool.acquire() as conn:
            async with conn.transaction():
                # Save task
                await conn.execute(
                    """
                    INSERT INTO tasks (task_id, title, description, status, collection, context, metadata, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (task_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        status = EXCLUDED.status,
                        context = EXCLUDED.context,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    task.task_id, task.title, task.description, task.status.value, 
                    task.collection, json.dumps(task.context), json.dumps(task.metadata)
                )
                
                # Save steps
                for step in task.steps:
                    await conn.execute(
                        """
                        INSERT INTO task_steps (step_id, task_id, description, status, result, started_at, completed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (step_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            result = EXCLUDED.result,
                            started_at = EXCLUDED.started_at,
                            completed_at = EXCLUDED.completed_at
                        """,
                        step.step_id, task.task_id, step.description, step.status.value,
                        step.result, step.started_at, step.completed_at
                    )

    async def get_task(self, task_id: str) -> Optional[Task]:
        if not self.pg.available:
            return None
            
        async with self.pg._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
            if not row:
                return None
            
            task = Task(
                task_id=row["task_id"],
                title=row["title"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                collection=row["collection"],
                context=json.loads(row["context"]),
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"].timestamp(),
                updated_at=row["updated_at"].timestamp()
            )
            
            step_rows = await conn.fetch("SELECT * FROM task_steps WHERE task_id = $1", task_id)
            for s in step_rows:
                step = TaskStep(
                    step_id=s["step_id"],
                    description=s["description"],
                    status=TaskStatus(s["status"]),
                    result=s["result"],
                    started_at=s["started_at"],
                    completed_at=s["completed_at"]
                )
                task.steps.append(step)
            
            return task

    async def list_tasks(self, collection: Optional[str] = None, status: Optional[TaskStatus] = None) -> List[Task]:
        if not self.pg.available:
            return []
            
        query = "SELECT task_id FROM tasks WHERE 1=1"
        params = []
        if collection:
            params.append(collection)
            query += f" AND collection = ${len(params)}"
        if status:
            params.append(status.value)
            query += f" AND status = ${len(params)}"
            
        async with self.pg._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            tasks = []
            for r in rows:
                t = await self.get_task(r["task_id"])
                if t:
                    tasks.append(t)
            return tasks

    async def create_checkpoint(self, checkpoint: TaskCheckpoint):
        if not self.pg.available:
            return
            
        async with self.pg._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO task_checkpoints (checkpoint_id, task_id, status, context_snapshot)
                VALUES ($1, $2, $3, $4)
                """,
                checkpoint.checkpoint_id, checkpoint.task_id, checkpoint.status.value,
                json.dumps(checkpoint.context_snapshot)
            )
