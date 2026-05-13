import logging
import time
from typing import Optional, Callable, Dict, Any
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep, TaskCheckpoint
from src.agent.tasks.task_store import TaskStore

logger = logging.getLogger(__name__)

class TaskOrchestrator:
    def __init__(self, task_store: TaskStore):
        self.store = task_store
        self._step_handlers: Dict[TaskStatus, Callable] = {}

    def register_handler(self, status: TaskStatus, handler: Callable):
        self._step_handlers[status] = handler

    async def create_task(self, title: str, description: str, collection: str) -> Task:
        task = Task(title=title, description=description, collection=collection)
        await self.store.save_task(task)
        return task

    async def run_step(self, task_id: str):
        """Mevcut task'ın bir sonraki adımını çalıştırır."""
        task = await self.store.get_task(task_id)
        if not task or task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.ABORTED):
            return task

        # Approval gate kontrolü
        if task.status == TaskStatus.WAITING_APPROVAL:
            logger.info(f"Task {task_id} onay bekliyor.")
            return task

        # Handler bul ve çalıştır
        handler = self._step_handlers.get(task.status)
        if not handler:
            logger.error(f"Status {task.status} için handler bulunamadı.")
            task.status = TaskStatus.FAILED
            await self.store.save_task(task)
            return task

        # Checkpoint oluştur (Hata durumunda geri dönebilmek için)
        await self.checkpoint(task)

        try:
            # Handler adım sonucunu ve yeni status'u döner
            result, next_status = await handler(task)
            
            # Task durumunu güncelle
            task.status = next_status
            task.updated_at = time.time()
            
            # Adımı güncelle (Eğer adımlı bir yapı ise)
            for step in task.steps:
                if step.status == TaskStatus.PLANNED:
                    step.status = TaskStatus.DONE
                    step.result = result
                    step.completed_at = time.time()
                    break
            
            await self.store.save_task(task)
            return task
        except Exception as e:
            logger.exception(f"Task {task_id} çalışırken hata oluştu.")
            task.status = TaskStatus.FAILED
            task.metadata["error"] = str(e)
            await self.store.save_task(task)
            return task

    async def checkpoint(self, task: Task):
        checkpoint = TaskCheckpoint(
            task_id=task.task_id,
            status=task.status,
            context_snapshot=task.context.copy()
        )
        await self.store.create_checkpoint(checkpoint)
        logger.info(f"Checkpoint oluşturuldu: {checkpoint.checkpoint_id} for task {task.task_id}")

    async def approve_task(self, task_id: str, next_status: TaskStatus = TaskStatus.EXECUTING):
        task = await self.store.get_task(task_id)
        if task and task.status == TaskStatus.WAITING_APPROVAL:
            task.status = next_status
            await self.store.save_task(task)
            return f"✅ Task {task_id} onaylandı, {next_status.value} aşamasına geçiliyor."
        return "⚠️ Onaylanacak uygun bir task bulunamadı."
