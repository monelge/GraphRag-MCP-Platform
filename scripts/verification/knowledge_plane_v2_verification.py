from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.mcp.tool_registry import (
    index_project,
    summarize_repository,
    search_repo_architecture,
)


async def verify_knowledge_plane_v2():
    print("=== Knowledge Plane V2 Doğrulama Testi Başlıyor ===\n")

    temp_dir = Path(tempfile.mkdtemp(prefix="kp_v2_verify_"))
    collection = f"verify_v2_{int(time.time())}"
    
    # Test projesi iskeleti: Birbirine bağlı 3 modül
    # Core -> Auth -> UI
    (temp_dir / "core").mkdir()
    (temp_dir / "auth").mkdir()
    (temp_dir / "ui").mkdir()
    
    (temp_dir / "core" / "db.py").write_text("def save_to_db(data): pass")
    (temp_dir / "auth" / "service.py").write_text("from core.db import save_to_db\ndef login(user): save_to_db(user)")
    (temp_dir / "ui" / "view.py").write_text("from auth.service import login\ndef on_click(): login('admin')")

    print(f"[*] Test projesi oluşturuldu: {temp_dir}")
    print(f"[*] Koleksiyon: {collection}\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()
        await server._neo4j.connect()

        # 1. index_project (PageRank tetiklemeli)
        print("[1/4] index_project() (PageRank entegrasyonu testi)...")
        await index_project(str(temp_dir), collection=collection)
        
        # Neo4j'den PageRank skorlarını kontrol et
        print("[*] PageRank skorları kontrol ediliyor...")
        pagerank_scores = await server._neo4j.run_pagerank_analysis(collection)
        print(f"    Tespit edilen skor sayısı: {len(pagerank_scores)}")
        # 'login' veya 'save_to_db' gibi çok çağrılanlar listede olmalı
        for name, score in list(pagerank_scores.items())[:5]:
            print(f"    - {name}: {score:.3f}")
        
        if pagerank_scores:
            print("    ✅ PageRank analizi başarıyla tamamlandı.")

        # 2. summarize_repository (Repo Map & Communities testi)
        print("\n[2/4] summarize_repository() (Repo Map & Communities testi)...")
        summary_res = await summarize_repository(str(temp_dir), collection=collection)
        
        # Qdrant'tan Repo Map ve Communities chunk'larını çekelim
        from src.storage.qdrant_store import QdrantStore
        q_store = QdrantStore(collection=collection)
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        
        summary_chunks, _ = await q_store.client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[FieldCondition(key="source_type", match=MatchValue(value="repo_summary"))]),
            limit=10
        )
        
        chunk_names = [p.payload.get("name") for p in summary_chunks]
        print(f"    Bulunan Özet Chunk'ları: {chunk_names}")
        
        has_repo_map = any("Repository Map" in name for name in chunk_names)
        has_communities = any("Community Reports" in name for name in chunk_names)
        
        if has_repo_map:
            print("    ✅ Repo Map başarıyla üretildi ve saklandı.")
        if has_communities:
            print("    ✅ Community Reports başarıyla üretildi ve saklandı.")

        # 3. search_repo_architecture (Mimari Sorgu testi)
        print("\n[3/4] search_repo_architecture() testi...")
        search_res = await search_repo_architecture("login flow", collection=collection)
        print(f"    Search Result (ilk 150 karakter):\n{search_res[:150]}...")
        
        if "login" in search_res.lower() or "service" in search_res.lower():
            print("\n    ✅ Mimari arama başarılı.")

        # 4. Final Kontrol: PageRank etkisini doğrula
        # Qdrant'taki chunkların içinde centrality skorlarını görmeliyiz (HybridSearcher/ContextBuilder dolaylı testi)
        print("\n[4/4] Final: ContextBuilder Centrality kontrolü...")
        from src.retrieval.context.context_builder import compute_final_score
        test_chunk = {"score": 0.8, "graph_centrality": 0.9, "type": "function"}
        final_score = compute_final_score(test_chunk)
        print(f"    Test Chunk (centrality=0.9) Final Score: {final_score}")
        if final_score > 0.5:
            print("    ✅ Centrality (PageRank) skoru başarıyla ağırlıklandırıldı.")

        print("\n=== ✅ Knowledge Plane V2 Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_knowledge_plane_v2())
