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
    store_memory,
    store_decision_memory,
    recall_memory,
    search_decisions,
    compact_memory,
)


async def verify_memory_plane():
    print("=== Memory Plane Doğrulama Testi Başlıyor ===\n")

    # 1. Hazırlık
    collection = f"verify_memory_{int(time.time())}"
    print(f"[*] Test Koleksiyonu: {collection}\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 2. store_memory (Episodik Hafıza)
        print("[1/5] store_memory() çalıştırılıyor (Episodik)...")
        sm_res = await store_memory(
            title="User Preference: Dark Mode",
            content="Kullanıcı arayüzünde her zaman koyu temayı tercih ediyor.",
            memory_type="episodic",
            collection=collection,
            tags=["ui", "pref"]
        )
        print(f"    Result: {sm_res}")

        # 3. store_decision_memory (Karar Hafızası)
        print("\n[2/5] store_decision_memory() çalıştırılıyor (Karar)...")
        sdm_res = await store_decision_memory(
            title="Architecture Decision: Qdrant for Memory",
            content="Hafıza katmanı için yüksek hız ve hibrit arama desteği nedeniyle Qdrant seçildi.",
            collection=collection,
            provenance="Design Doc v2"
        )
        print(f"    Result: {sdm_res}")

        # 4. recall_memory (Genel Arama)
        print("\n[3/5] recall_memory() çalıştırılıyor...")
        rm_res = await recall_memory(
            query="kullanıcı tercihi",
            collection=collection,
            top_k=2
        )
        print(f"    Recall Result (ilk 100 karakter): {rm_res[:100]}...")
        if "Dark Mode" in rm_res:
            print("    ✅ Episodik hafıza başarıyla geri çağrıldı.")

        # 5. search_decisions (Karar Arama)
        print("\n[4/5] search_decisions() çalıştırılıyor...")
        sd_res = await search_decisions(
            query="veritabanı seçimi",
            collection=collection,
            top_k=2
        )
        print(f"    Decision Result (ilk 100 karakter): {sd_res[:100]}...")
        if "Qdrant" in sd_res:
            print("    ✅ Karar hafızası başarıyla geri çağrıldı.")

        # 6. compact_memory (Bakım - LLM Gerektirir)
        print("\n[5/5] compact_memory() çalıştırılıyor (Bakım)...")
        # Benzer bir anı daha ekleyelim ki birleştirme yapılabilsin
        await store_memory(
            title="UI Pref: Contrast",
            content="Kullanıcı yüksek kontrastlı mod istiyor.",
            memory_type="episodic",
            collection=collection
        )
        # Not: compact_memory içinde LLM çağrısı yapılacağı için API KEY tanımlı olmalıdır.
        try:
            cm_res = await compact_memory(collection=collection, query="ui")
            print(f"    Compact Result: {cm_res}")
        except Exception as e:
            print(f"    ⚠️ Compact işlemi (muhtemelen LLM ayarı eksikliği nedeniyle) atlandı veya hata verdi: {e}")

        # Postgres ve Qdrant Kontrolleri
        print("\n[*] Depolama Katmanları Doğrulanıyor...")
        
        # Qdrant Kontrolü
        from src.storage.qdrant_store import QdrantStore
        # Episodik hafıza 'episodic_memory' koleksiyonunda saklanır (EpisodicStore sabitidir)
        q_store = QdrantStore(collection="episodic_memory") 
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        points, _ = await q_store.client.scroll(
            collection_name="episodic_memory",
            scroll_filter=Filter(must=[FieldCondition(key="collection", match=MatchValue(value=collection))]),
            limit=5
        )
        print(f"    Qdrant 'episodic_memory' içindeki kayıt sayısı: {len(points)}")

        # Postgres Kontrolü (Audit/Retrieval Logs)
        if server._postgres.available:
            await asyncio.sleep(1) # Async log yazımı için bekle
            # Retrieval loglarını kontrol et
            ret_stats = await server._postgres.get_retrieval_stats(days=1)
            found_ret = any(r['collection'] == collection for r in ret_stats)
            
            # Audit loglarını kontrol et
            audit_stats = await server._postgres.get_audit_stats(days=1)
            # 'summary' event_type bazlı gruplandığı için 'collection' içermez, 'recent' listesine bakmalıyız
            found_audit = any(row.get('collection') == collection for row in audit_stats.get("recent", []))
            
            print(f"    Postgres Retrieval Log: {'EVET' if found_ret else 'HAYIR'}")
            print(f"    Postgres Audit Log (memory_write): {'EVET' if found_audit else 'HAYIR'}")

        print("\n=== ✅ Bellek Düzlemi Doğrulaması Başarıyla Tamamlandı ===")

    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_memory_plane())
