from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

# MCP runtime ve araçlarını içe aktar
import src.mcp.server as server
from src.mcp.tool_registry import (
    index_project,
    incremental_index_project,
    search_repo_architecture,
    summarize_repository,
)


async def verify_knowledge_plane():
    print("=== Knowledge Plane Doğrulama Testi Başlıyor ===\n")

    # 1. Hazırlık: Geçici bir test projesi oluştur
    temp_dir = Path(tempfile.mkdtemp(prefix="kp_verify_"))
    collection = f"verify_{temp_dir.name}"
    
    test_file = temp_dir / "app.py"
    test_file.write_text("""
def calculate_total(items: list) -> float:
    \"\"\"Sepet toplamını hesaplar.\"\"\"
    return sum(item['price'] for item in items)

class ShoppingCart:
    def __init__(self):
        self.items = []
    
    def add_item(self, name: str, price: float):
        self.items.append({'name': name, 'price': price})
""")

    print(f"[*] Geçici proje oluşturuldu: {temp_dir}")
    print(f"[*] Koleksiyon: {collection}\n")

    try:
        # DB bağlantılarını lifespandaki gibi başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 2. index_project tetikle
        print("[1/4] index_project() çalıştırılıyor...")
        index_res = await index_project(str(temp_dir), collection=collection)
        print(f"    Result: {index_res}")

        # Neo4j Kontrolü
        print("[*] Neo4j doğrulanıyor...")
        nodes = await server._neo4j.execute_query(
            "MATCH (n) WHERE n.collection = $coll RETURN count(n) as count",
            {"coll": collection}
        )
        print(f"    Neo4j Node Sayısı: {nodes[0]['count']}")

        # Qdrant Kontrolü
        print("[*] Qdrant doğrulanıyor...")
        from src.storage.qdrant_store import QdrantStore
        q_store = QdrantStore(collection=collection)
        indexed_files = await q_store.get_indexed_file_paths()
        print(f"    Qdrant İndekslenen Dosyalar: {indexed_files}")

        # 3. incremental_index_project tetikle
        print("\n[2/4] incremental_index_project() çalıştırılıyor...")
        test_file.write_text(test_file.read_text() + "\n\ndef clear_cart(): pass\n")
        inc_res = await incremental_index_project(str(temp_dir), changed_files=[str(test_file)])
        print(f"    Result: {inc_res}")

        # 4. summarize_repository tetikle
        print("\n[3/4] summarize_repository() çalıştırılıyor...")
        sum_res = await summarize_repository(str(temp_dir), collection=collection)
        print(f"    Summary (ilk 100 karakter): {sum_res[:100]}...")

        # Redis/Registry Kontrolü
        print("[*] Project Registry doğrulanıyor...")
        profile = server._registry.get(collection)
        if profile:
            print(f"    Registry Kaydı: {profile.project_name} | Diller: {profile.languages}")

        # 5. search_repo_architecture tetikle
        print("\n[4/4] search_repo_architecture() çalıştırılıyor...")
        search_res = await search_repo_architecture("sepet hesaplama mantığı", collection=collection)
        print(f"    Search Result (ilk 100 karakter): {search_res[:100]}...")

        # Postgres Kontrolü (Retrieval Log)
        if server._postgres.available:
            print("[*] Postgres Retrieval Log doğrulanıyor...")
            # Kısa bir bekleme (async yazma için)
            await asyncio.sleep(1)
            rows = await server._postgres.get_retrieval_stats(days=1)
            found = any(r['collection'] == collection for r in rows)
            print(f"    Postgres Log Kaydı Bulundu mu: {'EVET' if found else 'HAYIR'}")

        print("\n=== ✅ Bilgi Düzlemi Doğrulaması Başarıyla Tamamlandı ===")

    finally:
        # Temizlik (Opsiyonel: Koleksiyonları silebiliriz ama görmek isterseniz kalsın)
        # shutil.rmtree(temp_dir)
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_knowledge_plane())
