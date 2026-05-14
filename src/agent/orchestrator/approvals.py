"""Approval gate davranışını orkestratörden ayıran yardımcı sınıf."""

from __future__ import annotations

from src.agent.tasks.task_models import TaskStatus
from src.agent.tasks.task_store import TaskStore


class ApprovalGate:
    """WAITING_APPROVAL durumundaki task'ların ilerlemesini yönetir."""

    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    async def approve(self, task_id: str, feedback: str = "approved") -> str:
        task = await self.task_store.get_task(task_id)
        if not task or task.status != TaskStatus.WAITING_APPROVAL:
            return "⚠️ Onaylanacak uygun bir task bulunamadı."
        task.context["approval_feedback"] = feedback
        task.status = TaskStatus.EXECUTING
        await self.task_store.save_task(task)
        return f"✅ Task {task_id} onaylandı, executing aşamasına geçiliyor."
