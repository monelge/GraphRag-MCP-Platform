import asyncio
import sys
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp_server as mcp
from src.mcp.server import _lifespan

async def test_all_tools():
    print("🚀 GraphRagMCP V2 Tool Uyumluluk Testi Başlıyor...")
    collection = "WareLogisticcBYS"
    project_path = "/projects/WareLogisticcBYS"
    
    # 1. Bağlantıları Kontrol Et
    print("\n--- [1] Bağlantı ve Durum ---")
    async with _lifespan(mcp.app):
        print("✅ Lifespan (DB Bağlantıları) Aktif.")
        
        try:
            # 2. Control Plane Araçları
            print("\n--- [2] Control Plane ---")
            projects = await mcp.list_projects()
            print(f"✅ list_projects: {projects[:100]}...")
            
            stats = await mcp.get_control_plane_stats()
            print(f"✅ get_control_plane_stats: {stats[:100]}...")
            
            # 3. Knowledge Plane Araçları
            print("\n--- [3] Knowledge Plane ---")
            # index_project uzun sürdüğü için sadece arama test ediyoruz (zaten indeksli varsayıyoruz)
            search_res = await mcp.search_code(query="TesellumController", collection=collection, top_k=2)
            print(f"✅ search_code: {search_res[:150]}...")
            
            explain_res = await mcp.explain_code(query="BarkodSorgula metodu ne yapar?", collection=collection)
            print(f"✅ explain_code: {explain_res[:150]}...")
            
            arch_res = await mcp.search_repo_architecture(query="Cari Extre servisi", collection=collection)
            print(f"✅ search_repo_architecture: {arch_res[:150]}...")
            
            # 4. Memory Plane Araçları
            print("\n--- [4] Memory Plane ---")
            store_res = await mcp.store_memory(
                title="Integration Test Note",
                content="Test content for verification.",
                collection=collection,
                tags=["test", "v2"]
            )
            print(f"✅ store_memory: {store_res}")
            
            recall_res = await mcp.recall_memory(query="Integration Test Note", collection=collection)
            print(f"✅ recall_memory: {recall_res[:150]}...")
            
            # Decision Memory
            d_store_res = await mcp.store_decision_memory(
                title="Test Decision",
                content="Decided to use V2 architecture.",
                collection=collection
            )
            print(f"✅ store_decision_memory: {d_store_res}")
            
            d_search_res = await mcp.search_decisions(query="V2 architecture", collection=collection)
            print(f"✅ search_decisions: {d_search_res[:150]}...")
            
            # 5. Execution Plane Araçları
            print("\n--- [5] Execution Plane ---")
            tasks = await mcp.list_agent_tasks(collection=collection)
            print(f"✅ list_agent_tasks: {tasks[:150]}...")
            
            # 6. Orchestration Plane
            print("\n--- [6] Orchestration Plane ---")
            # summarize_repository KP zenginleştirmesi kullandığı için kritik
            summary = await mcp.summarize_repository(project_path=project_path, collection=collection)
            print(f"✅ summarize_repository: {summary[:150]}...")

            print("\n" + "="*50)
            print("✨ TÜM ARAÇLAR BAŞARIYLA DOĞRULANDI!")
            print("="*50)

        except Exception as e:
            print(f"\n❌ HATA: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_all_tools())
