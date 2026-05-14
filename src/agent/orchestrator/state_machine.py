import logging
import time
from typing import Optional, Callable, Dict, Any
from src.agent.tasks.task_models import Task, TaskStatus, TaskStep, TaskCheckpoint
from src.agent.tasks.task_store import TaskStore
from src.storage.episodic_store import EpisodicStore, MemoryEntry

logger = logging.getLogger(__name__)

class TaskOrchestrator:
    """
    Görev yöneticisi — Task yaşam döngüsü ve handler execution.
    
    Faz 3 Özellikleri:
    - Memory lookup: Görev başında benzer deneyimleri ara
    - Learning: Başarılı adımları belleğe kaydet
    - Rollback: Checkpoint'dan restore mekanizması
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

    async def checkpoint(self, task: Task):
        """Checkpoint oluştur — geri dönüş için."""
        checkpoint = TaskCheckpoint(
            task_id=task.task_id,
            status=task.status,
            context_snapshot=task.context.copy()
        )
        await self.store.create_checkpoint(checkpoint)
        logger.info(f"Checkpoint oluşturuldu: {checkpoint.checkpoint_id} for task {task.task_id}")

    async def rollback_to_checkpoint(self, task_id: str, checkpoint_id: str) -> bool:
        """
        Faz 3: Belirtilen checkpoint'tan geri dön.
        Task context'i restore et, adımları reset et.
        
        Süreç:
        1. Checkpoint'ı yükle
        2. Task context'ini restore et
        3. Adımları PLANNED durumuna döndür
        4. Task status'unu RETRIEVING'e (başlangıç) döndür
        5. Veritabanına kaydet
        """
        task = await self.store.get_task(task_id)
        if not task:
            logger.warning(f"Rollback: Task bulunamadı ({task_id})")
            return False
        
        try:
            # Checkpoint'ları yükle ve belirtileni bul
            checkpoints = await self.store.get_checkpoints_by_task(task_id)
            target_checkpoint = None
            
            for cp in checkpoints:
                if cp.checkpoint_id == checkpoint_id:
                    target_checkpoint = cp
                    break
            
            if not target_checkpoint:
                logger.warning(f"Rollback: Checkpoint bulunamadı ({checkpoint_id})")
                return False
            
            # Context restore
            task.context = target_checkpoint.context_snapshot.copy()
            task.status = TaskStatus.PLANNED
            
            # İlk adımı reset et
            for i, step in enumerate(task.steps):
                if i == 0:
                    step.status = TaskStatus.PLANNED
                    step.result = None
                    step.completed_at = None
                    step.started_at = None
                    break
                else:
                    step.status = TaskStatus.PLANNED
                    step.result = None
                    step.completed_at = None
            
            # Metadata'ya rollback bilgisini ekle
            task.metadata["last_rollback"] = {
                "checkpoint_id": checkpoint_id,
                "timestamp": time.time(),
                "context_keys": list(task.context.keys())
            }
            
            await self.store.save_task(task)
            logger.info(f"✅ Rollback başarılı (task {task_id} → checkpoint {checkpoint_id})")
            return True
        except Exception as e:
            logger.error(f"Rollback hatası (task {task_id}): {e}")
            return False

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
