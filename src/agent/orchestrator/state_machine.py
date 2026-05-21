from __future__ import annotations

import logging
import time
from typing import Callable, Dict, Optional

from src.agent.nodes import DEFAULT_PIPELINE, NODE_REGISTRY
from src.agent.orchestrator.approvals import ApprovalGate
from src.agent.orchestrator.checkpoints import CheckpointStore
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep
from src.agent.tasks.task_store import TaskStore
from src.storage.episodic_store import EpisodicStore, MemoryEntry

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """FSM status'lerini koruyarak node pipeline çalıştıran orkestratör."""

    def __init__(
        self,
        task_store: TaskStore,
        episodic_store: Optional[EpisodicStore] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        app_context=None,
    ):
        self.store = task_store
        self.episodic = episodic_store
        self.checkpoint_store = checkpoint_store
        self.app_context = app_context
        self._step_handlers: Dict[TaskStatus, Callable] = {}
        self.approval_gate = ApprovalGate(task_store)

    def register_handler(self, status: TaskStatus, handler: Callable):
        self._step_handlers[status] = handler

    async def create_task(self, title: str, description: str, collection: str, steps=None) -> Task:
        task = Task(title=title, description=description, collection=collection)
        task.context.setdefault("current_node", DEFAULT_PIPELINE[0])
        for step_desc in steps or []:
            task.add_step(step_desc)
        await self.store.save_task(task)
        return task

    async def _lookup_related_memory(self, task: Task) -> Dict[str, object]:
        if not self.episodic:
            return {}
        try:
            query = f"{task.title} {task.description}"
            results = await self.episodic.search_memory(query, collection=task.collection, top_k=5)
            return {
                "count": len(results),
                "suggestions": [item.get("name", "")[:100] for item in results[:3]],
                "full_results": results,
            }
        except Exception as exc:
            logger.warning("Bellek lookup hatası (task %s): %s", task.task_id, exc)
            return {}

    def _status_to_node(self, status: TaskStatus) -> str:
        mapping = {
            TaskStatus.PLANNED: "planner",
            TaskStatus.RETRIEVING: "retriever",
            TaskStatus.ANALYZING: "explainer",
            TaskStatus.EXECUTING: "editor",
            TaskStatus.VERIFYING: "verifier",
            TaskStatus.SUMMARIZING: "summarizer",
        }
        return mapping.get(status, DEFAULT_PIPELINE[0])

    def _node_to_status(self, node_name: Optional[str]) -> TaskStatus:
        mapping = {
            "planner": TaskStatus.PLANNED,
            "retriever": TaskStatus.RETRIEVING,
            "explainer": TaskStatus.ANALYZING,
            "editor": TaskStatus.EXECUTING,
            "verifier": TaskStatus.VERIFYING,
            "reviewer": TaskStatus.VERIFYING,
            "summarizer": TaskStatus.SUMMARIZING,
            None: TaskStatus.DONE,
        }
        return mapping.get(node_name, TaskStatus.EXECUTING)

    async def _save_checkpoint(self, task: Task, current_node: str, step_index: int, conn=None, file_patches=None, command_results=None):
        if self.checkpoint_store:
            await self.checkpoint_store.save(
                task,
                current_node=current_node,
                step_index=step_index,
                file_patches=file_patches,
                command_results=command_results,
                conn=conn,
            )

    async def run_step(self, task_id: str):
        task = await self.store.get_task(task_id)
        if not task or task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.ABORTED):
            return task
        if task.status == TaskStatus.WAITING_APPROVAL:
            logger.info("Task %s onay bekliyor.", task_id)
            return task
        if self.episodic:
            task.context["related_memory"] = await self._lookup_related_memory(task)

        current_node = task.context.get("current_node") or self._status_to_node(task.status)
        task.context["current_node"] = current_node
        step_index = int(task.context.get("resume_from_step", task.context.get("current_step_index", 0)))

        node_cls = NODE_REGISTRY.get(current_node)
        if not node_cls:
            logger.error("Node bulunamadı: %s", current_node)
            task.status = TaskStatus.FAILED
            await self.store.save_task(task)
            return task

        node = node_cls()
        try:
            async with self.store.pg._pool.acquire() as conn:
                async with conn.transaction():
                    await self._save_checkpoint(task, current_node, step_index, conn=conn)
                    result = await node.run(task, self.app_context)
                    
                    # --- Agent Plane V2: Reflection Loop & Self-Correction ---
                    if not result.success and current_node in ["verifier", "reviewer"]:
                        # Maksimum deneme sayısını kontrol et (Loop önleme)
                        attempts = task.context.get("reflection_attempts", 0)
                        if attempts < 3:
                            logger.info("Task %s: %s başarısız, Reflection Loop başlatılıyor (Deneme %d/3)", task_id, current_node, attempts + 1)
                            task.context["reflection_attempts"] = attempts + 1
                            task.context["last_failure_feedback"] = result.output
                            result.next_node = "editor"  # Tekrar editor'e dön
                            task.status = TaskStatus.EXECUTING
                        else:
                            logger.warning("Task %s: Maksimum reflection denemesine ulaşıldı.", task_id)
                            task.status = TaskStatus.FAILED
                    
                    task.context.update(result.context_updates)
                    task.context["current_node"] = result.next_node

                    # V2: Planner tarafından üretilen adımları formal task.steps listesine işle
                    if "planned_steps" in result.context_updates and not task.steps:
                        for step_desc in result.context_updates["planned_steps"]:
                            task.add_step(step_desc)

                    # Node token kullanımını görev bağlamında biriktir
                    if result.token_usage > 0:
                        prev = task.context.get("total_token_usage", 0)
                        task.context["total_token_usage"] = prev + result.token_usage
                        node_tokens = task.context.setdefault("node_token_usage", {})
                        node_tokens[current_node] = node_tokens.get(current_node, 0) + result.token_usage
                    if result.file_patches:
                        task.context["file_patches"] = result.file_patches
                    if result.command_results:
                        task.context["command_results"] = result.command_results
                    if isinstance(result.output, str):
                        task.metadata["last_node_output"] = result.output
                    task.updated_at = time.time()
                    if result.next_node is None and task.status != TaskStatus.WAITING_APPROVAL:
                        task.status = TaskStatus.DONE
                    elif task.status != TaskStatus.WAITING_APPROVAL:
                        task.status = self._node_to_status(result.next_node)
                    for step in task.steps:
                        if step.status == TaskStatus.PLANNED:
                            step.status = TaskStatus.DONE if result.success else TaskStatus.FAILED
                            step.result = result.output
                            step.completed_at = time.time()
                            if self.episodic and result.success:
                                await self._learn_from_step(task, step, result.output)
                            break
                    await self.store.save_task(task, conn=conn)
                    await self._save_checkpoint(
                        task,
                        task.context.get("current_node") or current_node,
                        step_index,
                        conn=conn,
                        file_patches=result.file_patches,
                        command_results=result.command_results,
                    )
            return task
        except Exception as exc:
            logger.exception("Task %s çalışırken hata oluştu.", task_id)
            task.status = TaskStatus.FAILED
            task.metadata["error"] = str(exc)
            await self.store.save_task(task)
            return task

    async def _learn_from_step(self, task: Task, step: TaskStep, result: str):
        if not self.episodic:
            return
        try:
            memory_entry = MemoryEntry(
                title=f"Başarılı Adım: {step.description[:80]}",
                content=f"Görev: {task.title}\n\nAdım: {step.description}\n\nSonuç: {result[:500]}",
                memory_type="resolved_incident",
                collection=task.collection,
                tags=["task_learning", "successful_step"],
                task_id=task.task_id,
                step_id=step.step_id,
                provenance="auto-learned-from-execution",
            )
            await self.episodic.store_memory(memory_entry)
        except Exception as exc:
            logger.warning("Learning hatası (step %s): %s", step.step_id, exc)

    async def approve_task(self, task_id: str, feedback: str = "approved") -> str:
        return await self.approval_gate.approve(task_id, feedback)

    async def complete_task(self, task_id: str, note: str = "") -> str:
        task = await self.store.get_task(task_id)
        if not task:
            return f"❌ Görev bulunamadı: `{task_id}`"
        if task.status in (TaskStatus.DONE, TaskStatus.ABORTED):
            return f"ℹ️ Görev zaten `{task.status.value}` durumunda: `{task_id}`"
        previous = task.status.value
        task.status = TaskStatus.DONE
        task.updated_at = time.time()
        task.context["current_node"] = None
        if note:
            task.metadata["completion_note"] = note
        now = time.time()
        for step in task.steps:
            if step.status not in (TaskStatus.DONE, TaskStatus.ABORTED, TaskStatus.FAILED):
                step.status = TaskStatus.DONE
                step.completed_at = now
        await self.store.save_task(task)
        return f"✅ Görev `{task_id}` tamamlandı (`{previous}` → `done`)."
