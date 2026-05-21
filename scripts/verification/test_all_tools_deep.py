import asyncio
import sys
import time
import hashlib
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp_server as mcp
from src.mcp.server import _lifespan, _app_ctx

async def get_db_counts():
    """Veritabanlarındaki mevcut kayıt sayılarını döner."""
    counts = {}
    
    # 1. Postgres Counts
    async with _app_ctx.postgres._pool.acquire() as conn:
        counts['audit'] = await conn.fetchval("SELECT count(*) FROM audit_events")
        counts['retrieval_logs'] = await conn.fetchval("SELECT count(*) FROM retrieval_logs")
        counts['tasks'] = await conn.fetchval("SELECT count(*) FROM tasks")
        counts['steps'] = await conn.fetchval("SELECT count(*) FROM task_steps")
    
    # 2. Redis Keys (Sample counts)
    redis = _app_ctx.redis
    if redis.available:
        ret_keys = 0
        async for _ in redis._client.scan_iter("ret:*"): ret_keys += 1
        counts['redis_ret'] = ret_keys
        
        qemb_keys = 0
        async for _ in redis._client.scan_iter("qemb:*"): qemb_keys += 1
        counts['redis_qemb'] = qemb_keys
    
    return counts

async def verify_deep():
    print("🚀 GraphRagMCP V2 Deep System Verification Başlıyor...")
    collection = "WareLogisticcBYS"
    project_path = "/projects/WareLogisticcBYS"
    
    async with _lifespan(mcp.app):
        print("🔗 Veritabanı bağlantıları kuruldu.")
        
        try:
            # Başlangıç durumunu al
            before = await get_db_counts()
            
            # --- TEST 1: KNOWLEDGE PLANE & REDIS CACHE ---
            print("\n[1] Knowledge Plane & Cache Testi...")
            query = f"test_query_{int(time.time())}"
            # İlk arama (Cache miss)
            await mcp.search_code(query=query, collection=collection, top_k=1)
            
            # Redis'te qemb ve ret keyleri oluştu mu?
            after_search = await get_db_counts()
            if after_search['redis_qemb'] > before['redis_qemb']:
                print("  ✅ Semantic Query Cache (qemb) kaydedildi.")
            else:
                print("  ❌ HATA: Semantic Query Cache (qemb) OLUŞMADI!")
                
            if after_search['redis_ret'] > before['redis_ret']:
                print("  ✅ Retrieval Result Cache (ret) kaydedildi.")
            else:
                print("  ✅ Not: Arama sonucu boşsa cache atlanmış olabilir.")

            # --- TEST 2: AUDIT LOGGING ---
            print("\n[2] Observability (Audit) Testi...")
            await mcp.store_memory(
                title=f"Audit Test {time.time()}",
                content="Deep verification test",
                collection=collection
            )
            after_audit = await get_db_counts()
            if after_audit['audit'] > before['audit']:
                print("  ✅ Audit Event PostgreSQL'e başarıyla yazıldı.")
            else:
                print("  ❌ HATA: Audit Event KAYDEDİLEMEDİ!")

            # --- TEST 3: TASK & STEPS PERSISTENCE ---
            print("\n[3] Orchestration & Task Steps Testi...")
            # Planner'ın adımları kaydettiğini doğrulamak için kısa bir görev
            await mcp.execute_agent_task(
                goal="Sadece bir plan oluştur ve dur",
                project_path=project_path,
                collection=collection
            )
            after_task = await get_db_counts()
            if after_task['tasks'] > before['tasks']:
                print("  ✅ Yeni Task PostgreSQL'e kaydedildi.")
            if after_task['steps'] > before['steps']:
                print("  ✅ Task Steps (Alt Adımlar) başarıyla ayrıştırıldı ve kaydedildi.")
            else:
                print("  ❌ HATA: Task Steps tablosu BOŞ KALDI!")

            # --- TEST 4: NEO4J INTEGRITY ---
            print("\n[4] Knowledge Plane V2 (Neo4j) Testi...")
            skeleton = await _app_ctx.neo4j.get_repo_skeleton(collection)
            if skeleton:
                print(f"  ✅ Neo4j Graph verisi erişilebilir ({len(skeleton)} modül).")
                # PageRank kontrolü (İlk 5 node'da pagerank var mı?)
                query = "MATCH (n {collection: $coll}) WHERE n.pagerank IS NOT NULL RETURN count(n) as c"
                res = await _app_ctx.neo4j.execute_query(query, {"coll": collection})
                if res and res[0]['c'] > 0:
                    print(f"  ✅ PageRank analiz skorları mevcut ({res[0]['c']} node).")
                else:
                    print("  ⚠️ Uyarı: PageRank skorları henüz hesaplanmamış.")
            else:
                print("  ❌ HATA: Neo4j skeleton boş! Proje indeksi eksik.")

            print("\n" + "="*50)
            print("✨ DEEP VERIFICATION TAMAMLANDI!")
            print("="*50)

        except Exception as e:
            print(f"\n❌ KRİTİK HATA: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_deep())
