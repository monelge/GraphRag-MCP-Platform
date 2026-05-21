import logging
import time
from typing import Optional, List, Dict, Any
from src.handlers.context import AppContext
from src.agent.tasks.task_models import Task, TaskStatus
from src.agent.orchestrator.state_machine import TaskOrchestrator

logger = logging.getLogger(__name__)

class OrchestrationHandler:
    """
    Unified Orchestration Plane (V2).
    Knowledge, Memory, Agent, Execution ve Control katmanlarını tek bir akışta birleştirir.
    """

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.orchestrator = TaskOrchestrator(
            task_store=ctx.task_store,
            episodic_store=ctx.episodic,
            checkpoint_store=ctx.checkpoint_store,
            app_context=ctx
        )

    async def execute_agent_task(self, goal: str, project_path: str, collection: str = "") -> str:
        """
        Görevi alır, Research -> Strategy -> Execution -> Validation döngüsünü otonom koşturur.
        SOTA Hybrid State Machine + Blackboard yaklaşımı.
        """
        if not collection:
            from src.handlers.indexing_handler import IndexingHandler
            collection = IndexingHandler.project_collection_name(project_path)

        # 0. Pre-flight Indexing Check (Enforcement)
        if not self.ctx.registry.get_profile(collection):
            logger.info("Orchestration V2: Proje henüz indekslenmemiş. Otomatik indeksleme başlatılıyor: %s", collection)
            # IndexingHandler üzerinden tam indeksleme tetikle
            from src.handlers.control_handler import ControlHandler
            # AppContext içinde control_handler'ın initialize edildiğini varsayıyoruz
            if hasattr(self.ctx, "control_handler"):
                await self.ctx.control_handler.register_project(project_path, collection=collection)
            else:
                logger.warning("ControlHandler bulunamadı, otomatik indeksleme atlanıyor.")

        # 1. Blackboard (Shared Context) Hazırlığı
        logger.info("Orchestration V2: Blackboard hazırlanıyor - %s", goal)
        
        # 2. Görev Oluşturma
        task = await self.orchestrator.create_task(
            title=f"Autonomous Goal: {goal[:50]}",
            description=goal,
            collection=collection
        )
        task_id = task.task_id

        # 3. Otonom Döngü (Agentic Workflow)
        # Control Plane (Budget) her adımda StateMachine içinde denetlenir.
        # Agent Plane (Reflection) hata durumunda Editor'e geri döndürür.
        
        results_summary = []
        max_steps = 15 # Runaway loop önlemi
        step_count = 0
        
        try:
            while task.status not in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.ABORTED) and step_count < max_steps:
                step_count += 1
                current_node = task.context.get("current_node", "planner")
                
                logger.info("Orchestration V2: Step %d - Node: %s", step_count, current_node)
                
                # Her adım öncesi Control Plane Yield Analizi
                if self.ctx.budget_manager:
                    self.ctx.budget_manager.check_task(task_id, tokens_used=0) 

                task = await self.orchestrator.run_step(task_id)
                
                if task.metadata.get("last_node_output"):
                    results_summary.append(f"[{current_node}] {task.metadata['last_node_output'][:200]}...")

            if step_count >= max_steps:
                return f"⚠️ Görev çok uzun sürdü ({max_steps} adım). Güvenlik gereği durduruldu. Son durum: {task.status.value}"

            # 4. Final Raporlama
            if task.status == TaskStatus.DONE:
                final_output = task.metadata.get('last_node_output', 'Başarılı.')
                
                # Knowledge Plane V2: Başarılı görevi hafızaya (Decision Layer) işle
                try:
                    from src.memory.stores.decision_store import DecisionStore
                    ds = DecisionStore(self.ctx.episodic)
                    await ds.store_decision(
                        title=f"Task Success: {task.title}",
                        content=f"Hedef: {goal}\n\nSonuç: {final_output}",
                        collection=collection,
                        provenance="autonomous-execution-final-report",
                        task_id=task_id,
                        tags=["task_outcome", "success"]
                    )
                except Exception as mem_err:
                    logger.warning("Final memory storage failed: %s", mem_err)

                return (
                    f"✅ Görev başarıyla tamamlandı: '{goal}'\n\n"
                    f"**Özet Akış:**\n" + "\n".join(results_summary[-5:]) + "\n\n"
                    f"**Sonuç:** {final_output}"
                )
            else:
                error = task.metadata.get("error", "Bilinmeyen hata")
                return f"❌ Görev başarısız oldu ({task.status.value}): {error}"

        except Exception as e:
            logger.exception("Orchestration kritik hata")
            return f"❌ Orkestrasyon sırasında kritik hata oluştu: {e}"
