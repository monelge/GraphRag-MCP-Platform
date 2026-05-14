import logging
import time
from typing import Optional, Callable, Dict, Any
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep
from src.agent.tasks.task_store import TaskStore
from src.storage.episodic_store import EpisodicStore, MemoryEntry

logger = logging.getLogger(__name__)

class TaskOrchestrator:
    """
    Görev yöneticisi — Task yaşam döngüsü ve handler execution.
    Bellek lookup ve başarılı adım learning desteği içerir.
    """
    
    def __init__(self, task_store: TaskStore, episodic_store: Optional[EpisodicStore] = None):
        self.store = task_store
        self.episodic = episodic_store
        self._step_handlers: Dict[TaskStatus, Callable] = {}

    def register_handler(self, status: TaskStatus, handler: Callable):
        """Status'e ait handler'ı kaydet."""
        self._step_handlers[status] = handler

    async def create_task(
        self,
        title: str,
        description: str,
        collection: str,
        steps: list[str] | None = None,
    ) -> Task:
        """Yeni görev oluştur. steps verilirse her eleman bir TaskStep olarak eklenir."""
        task = Task(title=title, description=description, collection=collection)
        for step_desc in (steps or []):
            task.add_step(step_desc)
        await self.store.save_task(task)
        return task

    async def _lookup_related_memory(self, task: Task) -> Dict[str, Any]:
        """
        Faz 3: Task için ilgili bellek kayıtlarını ara.
        Başarılı geçmiş adımları ve benzer görev çözümlerini döner.
        """
        if not self.episodic:
            return {}
        
        try:
            # Görev başlığı ve açıklamasına benzer bellek kayıtlarını ara
            query = f"{task.title} {task.description}"
            results = await self.episodic.search_memory(
                query,
                collection=task.collection,
                top_k=5
            )
            
            related_memory = {
                "count": len(results),
                "suggestions": [r.get("name", "")[:100] for r in results[:3]],
                "full_results": results
            }
            
            logger.info(f"Task {task.task_id} için {len(results)} bellek kaydı bulundu")
            return related_memory
        except Exception as e:
            logger.warning(f"Bellek lookup hatası (task {task.task_id}): {e}")
            return {}

    async def run_step(self, task_id: str):
        """
        Mevcut task'ın bir sonraki adımını çalıştırır.
        
        Faz 3 İyileştirmeler:
        - Öncesi: İlgili bellek lookup
        - Sonrası: Başarılı adımları kaydet
        """
        task = await self.store.get_task(task_id)
        if not task or task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.ABORTED):
            return task

        # Approval gate kontrolü
        if task.status == TaskStatus.WAITING_APPROVAL:
            logger.info(f"Task {task_id} onay bekliyor.")
            return task

        # Faz 3: Adım öncesi bellek lookup
        if self.episodic:
            related_memory = await self._lookup_related_memory(task)
            task.context["related_memory"] = related_memory

        # Handler bul ve çalıştır
        handler = self._step_handlers.get(task.status)
        if not handler:
            logger.error(f"Status {task.status} için handler bulunamadı.")
            task.status = TaskStatus.FAILED
            await self.store.save_task(task)
            return task

        # Checkpoint oluştur kaldırıldı — run_step pipeline aktif olmadığından gereksiz

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
                    
                    # Faz 3: Başarılı adımı belleğe kaydet
                    if self.episodic and next_status != TaskStatus.FAILED:
                        await self._learn_from_step(task, step, result)
                    break
            
            await self.store.save_task(task)
            return task
        except Exception as e:
            logger.exception(f"Task {task_id} çalışırken hata oluştu.")
            task.status = TaskStatus.FAILED
            task.metadata["error"] = str(e)
            await self.store.save_task(task)
            return task

    async def _learn_from_step(self, task: Task, step: TaskStep, result: str):
        """
        Faz 3: Başarılı adımdan öğren ve belleğe kaydet.
        Gelecekte benzer görevler için tavsiye oluşturur.
        """
        if not self.episodic:
            return
        
        try:
            memory_entry = MemoryEntry(
                title=f"Başarılı Adım: {step.description[:80]}",
                content=f"Görev: {task.title}\n\nAdım: {step.description}\n\nSonuç: {result[:500]}",
                memory_type="resolved_incident",
                collection=task.collection,
                tags=["task_learning", "successful_step"],
                # Faz 3: Task Linkage
                task_id=task.task_id,
                step_id=step.step_id,
                provenance=f"auto-learned-from-execution"
            )
            
            await self.episodic.store_memory(memory_entry)
            logger.info(f"Adım {step.step_id} belleğe kaydedildi (task {task.task_id})")
        except Exception as e:
            logger.warning(f"Learning hatası (step {step.step_id}): {e}")

    async def approve_task(self, task_id: str, next_status: TaskStatus = TaskStatus.EXECUTING):
        """Task onayı — WAITING_APPROVAL'dan ilerle."""
        task = await self.store.get_task(task_id)
        if task and task.status == TaskStatus.WAITING_APPROVAL:
            task.status = next_status
            await self.store.save_task(task)
            return f"✅ Task {task_id} onaylandı, {next_status.value} aşamasına geçiliyor."
        return "⚠️ Onaylanacak uygun bir task bulunamadı."

    async def complete_task(self, task_id: str, note: str = "") -> str:
        """
        Herhangi bir durumdan görevi DONE'a çeker (manuel tamamlama).
        Zaten DONE veya ABORTED olan task'lara dokunulmaz.
        note: İsteğe bağlı tamamlama notu (metadata'ya kaydedilir).
        """
        task = await self.store.get_task(task_id)
        if not task:
            return f"❌ Görev bulunamadı: `{task_id}`"
        if task.status in (TaskStatus.DONE, TaskStatus.ABORTED):
            return f"ℹ️ Görev zaten `{task.status.value}` durumunda: `{task_id}`"

        previous = task.status.value
        task.status = TaskStatus.DONE
        task.updated_at = time.time()
        if note:
            task.metadata["completion_note"] = note

        # Tamamlanmamış adımları da done'a çek
        now = time.time()
        for step in task.steps:
            if step.status not in (TaskStatus.DONE, TaskStatus.ABORTED, TaskStatus.FAILED):
                step.status = TaskStatus.DONE
                step.completed_at = now

        await self.store.save_task(task)
        logger.info("Görev manuel tamamlandı: %s (%s → done)", task_id, previous)
        return f"✅ Görev `{task_id}` tamamlandı (`{previous}` → `done`)."
