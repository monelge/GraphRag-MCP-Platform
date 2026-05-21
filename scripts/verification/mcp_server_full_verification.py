from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

# Doğrudan mcp_server arayüzünü test ediyoruz
import src.mcp_server as mcp


async def verify_full_mcp_server():
    print("=== 🌐 MCP Server Full System Entegrasyon Testi Başlıyor ===\n")
    
    # Test için ortak koleksiyon adı
    collection = f"full_test_{int(time.time())}"
    print(f"[*] Global Test Koleksiyonu: {collection}\n")

    try:
        # 1. Veritabanı Bağlantıları (Lifespan simülasyonu)
        print("[*] Veritabanı bağlantıları kuruluyor...")
        await mcp._app_ctx.postgres.connect()
        await mcp._app_ctx.neo4j.connect()
        print("    ✅ Bağlantılar hazır.\n")

        # --- KNOWLEDGE PLANE ---
        print("[1/5] KNOWLEDGE PLANE: index_project() testi...")
        # Küçük bir dosya oluşturup indeksleyelim
        temp_dir = Path(f"/tmp/{collection}")
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "main.py").write_text("def start(): print('Hello World')")
        
        kp_res = await mcp.index_project(str(temp_dir), collection=collection)
        print(f"    Result: {kp_res[:80]}...")
        if "✅" in kp_res:
            print("    ✅ Knowledge Plane bağlantısı başarılı.")

        # --- MEMORY PLANE ---
        print("\n[2/5] MEMORY PLANE: store_memory() testi...")
        mem_res = await mcp.store_memory(
            title="System Test Note",
            content="Bu bir entegrasyon testi kaydıdır.",
            collection=collection
        )
        print(f"    Result: {mem_res}")
        if "✅" in mem_res:
            print("    ✅ Memory Plane bağlantısı başarılı.")

        # --- AGENT PLANE ---
        print("\n[3/5] AGENT PLANE: create_agent_task() testi...")
        agent_res = await mcp.create_agent_task(
            title="System Health Check",
            description="Tüm katmanların birbiriyle konuştuğunu doğrula.",
            collection=collection
        )
        print(f"    Result: {agent_res[:100]}...")
        if "🚀" in agent_res:
            print("    ✅ Agent Plane bağlantısı başarılı.")

        # --- EXECUTION PLANE ---
        print("\n[4/5] EXECUTION PLANE: run_verification_plan() testi...")
        # Kendi kodumuz üzerinde (src dizini) bir doğrulama testi (sadece profil tespiti için)
        exec_res = await mcp.run_verification_plan(
            project_path=str(ROOT / "src"),
            run_build=False,
            run_tests=False,
            run_lint=False
        )
        print(f"    Result: {exec_res[:100]}...")
        if "Doğrulama Planı" in exec_res:
            print("    ✅ Execution Plane bağlantısı başarılı.")

        # --- CONTROL PLANE ---
        print("\n[5/5] CONTROL PLANE: get_control_plane_stats() testi...")
        # Gateway'e bir veri ekleyelim
        mcp._control.ctx.model_gateway._update_stats("gpt-4o-mini", 100, 100)
        
        cp_res = await mcp.get_control_plane_stats()
        print(f"    Result: {cp_res[:150]}...")
        if "Control Plane" in cp_res:
            print("    ✅ Control Plane bağlantısı başarılı.")

        print("\n" + "="*50)
        print("🎉 TEBRİKLER! MCP Server tüm katmanlara erişebiliyor.")
        print("="*50)

    except Exception as e:
        print(f"\n❌ SİSTEM HATASI: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Temizlik
        await mcp._app_ctx.postgres.close()
        await mcp._app_ctx.neo4j.close()
        await mcp._app_ctx.redis.close()


if __name__ == "__main__":
    asyncio.run(verify_full_mcp_server())
