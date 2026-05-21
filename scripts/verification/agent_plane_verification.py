from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

# MCP runtime ve araçlarını içe aktar
import src.mcp.server as server
from src.mcp.tool_registry import (
    create_agent_task,
    get_task_status,
    approve_task_step,
    resume_task,
    list_agent_tasks,
)


async def verify_agent_plane():
    print("=== Agent Plane Doğrulama Testi Başlıyor ===\n")

    collection = f"verify_agent_{int(time.time())}"
    print(f"[*] Test Koleksiyonu: {collection}\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 0. Koleksiyon Hazırlığı (Qdrant'ta koleksiyonun var olduğundan emin ol)
        print("[0/5] Koleksiyon hazırlanıyor...")
        from src.storage.qdrant_store import QdrantStore
        q_store = QdrantStore(collection=collection)
        await q_store.ensure_collection()
        print(f"    ✅ Koleksiyon hazır: {collection}")
        
        # 1. create_agent_task (Görev Oluşturma ve Başlatma)
        print("[1/5] create_agent_task() çalıştırılıyor...")
        create_res = await create_agent_task(
            title="Verify System Integration",
            description="Knowledge, Memory ve Agent plane katmanlarını doğrula.",
            collection=collection,
            steps=["Planner kontrolü", "Checkpoint testi", "Final özet"]
        )
        print(f"    Result: {create_res[:200]}...")
        
        # Task ID'yi çıktıdan çekelim (Basit bir parsing)
        task_id = None
        for line in create_res.split("\n"):
            if "Task ID:" in line:
                task_id = line.split("`")[1]
                break
        
        if not task_id:
            print("    ❌ Task ID alınamadı, test durduruluyor.")
            return

        print(f"    ✅ Görev oluşturuldu: {task_id}")

        # 2. get_task_status (Durum Sorgulama)
        print("\n[2/5] get_task_status() çalıştırılıyor...")
        status_res = await get_task_status(task_id)
        print(f"    Mevcut Durum: {status_res[:150]}...")

        # 3. list_agent_tasks (Görev Listeleme)
        print("\n[3/5] list_agent_tasks() çalıştırılıyor...")
        list_res = await list_agent_tasks(collection=collection)
        if task_id in list_res:
            print(f"    ✅ Görev listede bulundu.")
        else:
            print(f"    ❌ Görev listede bulunamadı!")

        # 4. Checkpoint Doğrulaması (Postgres)
        print("\n[*] Postgres Checkpoint ve Task Kaydı Doğrulanıyor...")
        if server._postgres.available:
            # Task tablosu kontrolü
            task_row = await server._postgres._pool.fetchrow(
                "SELECT status, context FROM tasks WHERE task_id = $1", task_id
            )
            print(f"    DB Status: {task_row['status']}")
            
            # Checkpoint kontrolü
            cp_rows = await server._postgres._pool.fetch(
                "SELECT current_node, step_index FROM task_checkpoints WHERE task_id = $1", task_id
            )
            print(f"    Bulunan Checkpoint Sayısı: {len(cp_rows)}")
            if cp_rows:
                print(f"    Son Node: {cp_rows[0]['current_node']}")

        # 5. approve_task_step veya resume_task simülasyonu
        # Eğer ajan onay bekliyorsa onaylayalım, beklemiyorsa resume deneyelim
        if "waiting_approval" in status_res.lower():
            print("\n[4/5] approve_task_step() çalıştırılıyor (Onay Bekleniyor)...")
            approve_res = await approve_task_step(task_id, feedback="Onaylandı, devam et.")
            print(f"    Approve Result: {approve_res}")
        else:
            print("\n[4/5] resume_task() denemesi (Checkpoint Testi)...")
            # Manuel olarak bir node'u geriye çekip resume edelim (test amaçlı)
            task = await server._task_store.get_task(task_id)
            task.context["current_node"] = "planner" 
            await server._task_store.save_task(task)
            
            resume_res = await resume_task(task_id)
            print(f"    Resume Result: {resume_res}")

        print("\n[5/5] Final Durum Kontrolü...")
        final_status = await get_task_status(task_id)
        print(f"    Final Status: {final_status[:100]}...")

        print("\n=== ✅ Ajan Düzlemi Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_agent_plane())
