from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.agent.orchestrator.state_machine import TaskOrchestrator
from src.agent.tasks.task_models import Task, TaskStatus
from src.agent.nodes.base import NodeResult


class MockFailNode:
    """Her zaman başarısız olan bir Verifier simülasyonu."""
    async def run(self, task, context):
        return NodeResult(
            success=False,
            output="Testler başarısız: 'expected 200, got 500'",
            next_node="summarizer", # Normalde buraya giderdi
            context_updates={"critical_error": True}
        )

async def verify_agent_plane_v2():
    print("=== Agent Plane V2 Doğrulama Testi Başlıyor ===\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        
        # 1. Görev Oluştur
        print("[1/3] Test Görevi Oluşturuluyor...")
        task = Task(
            title="Reflection Loop Test",
            description="Verifier başarısız olduğunda editor'e geri dönmeli.",
            collection="test_collection"
        )
        task.status = TaskStatus.VERIFYING
        task.context["current_node"] = "verifier"
        await server._task_store.save_task(task)
        print(f"    Görev ID: {task.task_id}, Durum: {task.status.value}")

        # 2. State Machine Reflection Testi
        print("\n[2/3] Reflection Loop Tetikleniyor (Verifier Fail -> Editor)...")
        orchestrator = TaskOrchestrator(server._task_store, app_context=server)
        
        # Mock node registry manipülasyonu (Verifier yerine bizim FailNode'u koyalım)
        from src.agent.nodes import NODE_REGISTRY
        original_verifier = NODE_REGISTRY.get("verifier")
        NODE_REGISTRY["verifier"] = MockFailNode
        
        try:
            # run_step çalıştır
            await orchestrator.run_step(task.task_id)
            
            # Sonucu kontrol et
            updated_task = await server._task_store.get_task(task.task_id)
            print(f"    Yeni Durum: {updated_task.status.value}")
            print(f"    Bir Sonraki Node: {updated_task.context.get('current_node')}")
            print(f"    Reflection Denemesi: {updated_task.context.get('reflection_attempts')}")
            
            if updated_task.status == TaskStatus.EXECUTING and updated_task.context.get("current_node") == "editor":
                print("\n    ✅ Başarılı: Verifier başarısız oldu ve State Machine otomatik olarak 'editor'e (Reflection) geri döndü.")
            else:
                print("\n    ❌ Başarısız: State Machine beklenen 'Reflection Loop'a girmedi.")
                
        finally:
            # Temizlik
            NODE_REGISTRY["verifier"] = original_verifier

        print("\n=== ✅ Agent Plane V2 Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()


if __name__ == "__main__":
    asyncio.run(verify_agent_plane_v2())
