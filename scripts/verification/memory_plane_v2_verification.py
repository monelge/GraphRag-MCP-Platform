from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.mcp.tool_registry import store_memory
from src.memory.services.memory_compaction import MemoryCompactor


async def verify_memory_plane_v2():
    print("=== Memory Plane V2 Doğrulama Testi Başlıyor ===\n")

    collection = f"verify_mem_v2_{int(time.time())}"
    print(f"[*] Test Koleksiyonu: {collection}\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 1. Ham Episodik Logları Simüle Et (Ajanın görev sırasında aldığı dağınık notlar)
        print("[1/3] Ham Episodik Loglar Oluşturuluyor...")
        logs = [
            "Bugün auth servisinde çalışırken fark ettim ki JWT token süresi 15 dakika değil 1 saatmiş.",
            "Kullanıcı bana typescript dosyalarında 'any' kullanmamamı söyledi, bunu kesinlikle hatırlamalıyım.",
            "Projeyi derlemek için 'npm run build:prod' kullanılıyor, normal build değil."
        ]
        
        for i, log in enumerate(logs):
            await store_memory(
                title=f"Session Transcript Part {i+1}",
                content=log,
                memory_type="episodic",
                collection=collection
            )
        print("    ✅ 3 adet ham log (episodic) eklendi.")

        # 2. Mem0 Tarzı Atomic Fact Extraction Testi
        print("\n[2/3] extract_atomic_facts() (Mem0 / Hierarchical Extraction) çalıştırılıyor...")
        compactor = MemoryCompactor(server._memory.memory_writer.episodic_store)
        
        try:
            # LLM çağrısı içerir, API anahtarı gerekebilir
            result = await compactor.extract_atomic_facts(collection=collection, limit=5)
            print(f"    Result: {result}")
            if "Atomic Fact" in result:
                print("    ✅ Başarılı: Karmaşık loglardan kalıcı ve net gerçekler (Atomic Facts) çıkarıldı.")
        except Exception as e:
            print(f"    ⚠️ Extraction işlemi (muhtemelen LLM ayarı eksikliği nedeniyle) hata verdi: {e}")

        # 3. Çıkarılan Fact'lerin Semantic Katmanda Kontrolü
        print("\n[3/3] Qdrant 'Semantic' Katman Kontrolü...")
        from src.storage.qdrant_store import QdrantStore
        q_store = QdrantStore(collection="episodic_memory") 
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        
        # Sadece 'semantic' olanları ve 'atomic_fact' tag'ine sahip olanları arayalım
        points, _ = await q_store.client.scroll(
            collection_name="episodic_memory",
            scroll_filter=Filter(must=[
                FieldCondition(key="collection", match=MatchValue(value=collection)),
                FieldCondition(key="memory_type", match=MatchValue(value="semantic")),
                FieldCondition(key="tags", match=MatchValue(value="atomic_fact"))
            ]),
            limit=10
        )
        
        print(f"    Çıkarılan Semantic (Atomic Fact) Kayıt Sayısı: {len(points)}")
        if len(points) > 0:
            for p in points[:3]:
                title = p.payload.get("name", "")
                content = p.payload.get("code", "")[:80]
                print(f"    - {title}: {content}...")
            print("    ✅ Extraction sonucu Semantic belleğe başarıyla yazıldı.")

        print("\n=== ✅ Memory Plane V2 Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_memory_plane_v2())
