import json
import logging
import asyncpg
from typing import List, Optional
from src.storage.postgres_store import PostgresStore
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep, TaskCheckpoint

logger = logging.getLogger(__name__)

class TaskStore:
    """
    Task ve checkpoint'leri PostgreSQL'de saklayan asynchronous depo.
    
    Faz 2 İyileştirmeler:
    - Error handling: Task bulunamadığında graceful fallback
    - SQL parametrization: Türkçe karakterleri güvenli işleme
    - Transaction safety: Atomik işlemler
    - Logging: Hata takibi için detaylı log
    """
    
    def __init__(self, pg_store: PostgresStore):
        self.pg = pg_store

    async def save_task(self, task: Task) -> bool:
        """
        Görevi ve adımlarını veritabanına kaydeder.
        Başarı durumunu döner (True/False).
        
        Faz 2: 
        - Türkçe başlık/açıklama desteği ✓ (JSON encoding)
        - Transaction wrapper ile atomic işlem ✓
        """
        if not self.pg.available:
            logger.warning("PostgreSQL kullanılamıyor, task %s kaydedilemiyor", task.task_id)
            return False
        
        try:
            async with self.pg._pool.acquire() as conn:
                async with conn.transaction():
                    # Görevi kaydet
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
                        task.task_id, 
                        task.title,  # Türkçe karakterleri destekler
                        task.description, 
                        task.status.value, 
                        task.collection, 
                        json.dumps(task.context, ensure_ascii=False),  # Türkçe JSON
                        json.dumps(task.metadata, ensure_ascii=False)
                    )
                    
                    # Adımları kaydet
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
                            step.step_id, 
                            task.task_id, 
                            step.description,  # Türkçe karakterleri destekler
                            step.status.value,
                            step.result, 
                            step.started_at, 
                            step.completed_at
                        )
            return True
        except asyncpg.PostgresError as e:
            logger.error("Task %s kaydedilirken PostgreSQL hatası: %s", task.task_id, str(e))
            return False
        except Exception as e:
            logger.error("Task %s kaydedilirken beklenmeyen hata: %s", task.task_id, str(e))
            return False

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        Belirtilen ID'ye sahip görevi yükler.
        Bulunamazsa None döner (graceful fallback).
        """
        if not self.pg.available:
            logger.debug("PostgreSQL kullanılamıyor, task %s yüklenemedi", task_id)
            return None
        
        try:
            async with self.pg._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
                if not row:
                    logger.warning("Task bulunamadı: %s", task_id)
                    return None
                
                # Context ve metadata JSON'dan parse et
                context = json.loads(row["context"]) if row["context"] else {}
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                
                task = Task(
                    task_id=row["task_id"],
                    title=row["title"],
                    description=row["description"],
                    status=TaskStatus(row["status"]),
                    collection=row["collection"],
                    context=context,
                    metadata=metadata,
                    created_at=row["created_at"].timestamp(),
                    updated_at=row["updated_at"].timestamp()
                )
                
                # Adımları yükle
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
        except asyncpg.PostgresError as e:
            logger.error("Task %s yüklenirken PostgreSQL hatası: %s", task_id, str(e))
            return None
        except (ValueError, KeyError) as e:
            logger.error("Task %s verisi parse edilirken hata: %s", task_id, str(e))
            return None
        except Exception as e:
            logger.error("Task %s yüklenirken beklenmeyen hata: %s", task_id, str(e))
            return None

    async def list_tasks(self, collection: Optional[str] = None, status: Optional[TaskStatus] = None) -> List[Task]:
        """
        Filtrelere göre görevleri listeler.
        Türkçe collection adlarını destekler.
        """
        if not self.pg.available:
            logger.debug("PostgreSQL kullanılamıyor, görevler listelenemedi")
            return []
        
        try:
            # Parametreli sorgu ile SQL injection önle
            where_clauses = []
            params = []
            
            if collection:
                where_clauses.append(f"collection = ${len(params) + 1}")
                params.append(collection)
            
            if status:
                where_clauses.append(f"status = ${len(params) + 1}")
                params.append(status.value)
            
            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
            query = f"SELECT task_id FROM tasks WHERE {where_clause}"
            
            async with self.pg._pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                tasks = []
                for r in rows:
                    t = await self.get_task(r["task_id"])
                    if t:
                        tasks.append(t)
                return tasks
        except asyncpg.PostgresError as e:
            logger.error("Görevler listelenirken PostgreSQL hatası: %s", str(e))
            return []
        except Exception as e:
            logger.error("Görevler listelenirken beklenmeyen hata: %s", str(e))
            return []

    async def create_checkpoint(self, checkpoint: TaskCheckpoint) -> bool:
        """
        Görev checkpoint'i oluşturur.
        Context snapshot'ı JSONB olarak kaydeder.
        """
        if not self.pg.available:
            logger.warning("PostgreSQL kullanılamıyor, checkpoint %s kaydedilemiyor", checkpoint.checkpoint_id)
            return False
        
        try:
            async with self.pg._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO task_checkpoints (checkpoint_id, task_id, status, context_snapshot)
                    VALUES ($1, $2, $3, $4)
                    """,
                    checkpoint.checkpoint_id, 
                    checkpoint.task_id, 
                    checkpoint.status.value,
                    json.dumps(checkpoint.context_snapshot, ensure_ascii=False)
                )
            return True
        except asyncpg.PostgresError as e:
            logger.error("Checkpoint %s kaydedilirken PostgreSQL hatası: %s", checkpoint.checkpoint_id, str(e))
            return False
        except Exception as e:
            logger.error("Checkpoint %s kaydedilirken beklenmeyen hata: %s", checkpoint.checkpoint_id, str(e))
            return False

    async def get_checkpoints_by_task(self, task_id: str) -> List[TaskCheckpoint]:
        """
        Faz 3: Belirtilen task ID'ye ait tüm checkpoint'ları döner.
        Oluşturulma zamanına göre DESC sıralanmış.
        """
        if not self.pg.available:
            logger.debug("PostgreSQL kullanılamıyor, checkpoint'lar yüklenemedi")
            return []
        
        try:
            async with self.pg._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM task_checkpoints 
                    WHERE task_id = $1 
                    ORDER BY created_at DESC
                    """,
                    task_id
                )
                
                checkpoints = []
                for row in rows:
                    context_snapshot = json.loads(row["context_snapshot"]) if row["context_snapshot"] else {}
                    checkpoint = TaskCheckpoint(
                        checkpoint_id=row["checkpoint_id"],
                        task_id=row["task_id"],
                        status=TaskStatus(row["status"]),
                        context_snapshot=context_snapshot,
                        created_at=row["created_at"].timestamp()
                    )
                    checkpoints.append(checkpoint)
                
                logger.info(f"Task {task_id} için {len(checkpoints)} checkpoint bulundu")
                return checkpoints
        except asyncpg.PostgresError as e:
            logger.error("Checkpoint'lar yüklenirken PostgreSQL hatası (task %s): %s", task_id, str(e))
            return []
        except (ValueError, KeyError) as e:
            logger.error("Checkpoint verisi parse edilirken hata (task %s): %s", task_id, str(e))
            return []
        except Exception as e:
            logger.error("Checkpoint'lar yüklenirken beklenmeyen hata (task %s): %s", task_id, str(e))
            return []

    async def delete_old_checkpoints(self, task_id: str, keep_count: int = 10) -> int:
        """
        Faz 3: Eski checkpoint'ları sil, yalnızca son keep_count'u sakla.
        Compaction stratejisi: DB boyutunu kontrolde tut.
        """
        if not self.pg.available:
            logger.debug("PostgreSQL kullanılamıyor, cleanup yapılamadı")
            return 0
        
        try:
            async with self.pg._pool.acquire() as conn:
                # Silinecek checkpoint'ları bul
                delete_result = await conn.execute(
                    """
                    DELETE FROM task_checkpoints 
                    WHERE checkpoint_id IN (
                        SELECT checkpoint_id FROM task_checkpoints 
                        WHERE task_id = $1 
                        ORDER BY created_at DESC 
                        LIMIT -1 OFFSET $2
                    )
                    """,
                    task_id,
                    keep_count
                )
                
                # asyncpg'de DELETE sonucu string formatında döner "DELETE X"
                deleted_count = int(delete_result.split()[-1]) if delete_result else 0
                logger.info(f"Task {task_id}: {deleted_count} eski checkpoint silindi (keep_count={keep_count})")
                return deleted_count
        except Exception as e:
            logger.error("Checkpoint cleanup hatası (task %s): %s", task_id, str(e))
            return 0
