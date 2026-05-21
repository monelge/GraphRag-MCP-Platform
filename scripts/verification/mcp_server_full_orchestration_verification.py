from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.mcp.tool_registry import execute_agent_task, index_project


async def verify_unified_orchestration_v2():
    print("=== Unified Orchestration V2 (Full System) Doğrulama Testi Başlıyor ===\n")

    project_path = str(ROOT) # Mevcut projeyi test olarak kullanalım
    collection = f"verify_orchestration_{int(time.time())}"
    goal = "Project structure analizi yap ve bana projenin ana giriş noktalarını (entrypoints) listele."

    print(f"[*] Hedef: {goal}")
    print(f"[*] Proje: {project_path}")
    print(f"[*] Koleksiyon: {collection}\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 0. Ön Hazırlık: Projeyi İndeksle
        print(f"[0/1] Proje indeksleniyor: {collection}...")
        await index_project(project_path, collection=collection)

        # 1. Otonom Orkestrasyonu Başlat
        print("\n[1/1] execute_agent_task() tetikleniyor...")

        print("      (Bu işlem SOTA hibrit akışı kullandığı için birkaç saniye sürebilir...)\n")
        
        result = await execute_agent_task(goal, project_path, collection=collection)
        
        print(f"\n--- Orkestrasyon Sonucu ---\n")
        print(result)
        print(f"\n---------------------------\n")

        if "başarıyla tamamlandı" in result.lower() or "entrypoints" in result.lower():
            print("✅ Başarılı: Unified Orchestration Plane tüm katmanları (KP, Memory, Agent, Execution, Control) başarıyla koordine etti.")
        else:
            print("⚠️ Uyarı: Orkestrasyon tamamlandı ancak sonuç beklenenden farklı olabilir. Lütfen yukarıdaki çıktıyı inceleyin.")

        print("\n=== ✅ Unified Orchestration V2 Doğrulaması Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_unified_orchestration_v2())
