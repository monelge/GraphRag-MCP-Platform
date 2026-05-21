#!/usr/bin/env python3
"""
GraphMCP — V2 Proje İndeksleme Scripti

Bu script, Knowledge Plane V2 standartlarına uygun olarak projeyi indeksler:
1. AST ve Graph çıkarma işlemi (Neo4j ve Qdrant).
2. PageRank analizi ile mimari önem skorlarının (centrality) hesaplanması.
3. Project Intelligence (Repo Map ve Community Reports) verilerinin üretilmesi.

Kullanım:
    docker exec -it graph-mcp python3 /app/scripts/index_v2.py \
        --project Vendoris \
        --path /projects/Vendoris
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Proje kök dizinini Python path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "/app")

from src.mcp.server import app, _lifespan
from src.mcp.tool_registry import index_project

async def run(project_name: str, project_path: str, batch_size: int) -> None:
    print(f"🚀 GraphRagMCP V2 İndeksleme Başlıyor...")
    print(f"📦 Koleksiyon: {project_name}")
    print(f"📂 Yol: {project_path}")
    print("-" * 50)

    # _lifespan ile gerekli DB bağlantılarını (Postgres, Neo4j, vs.) güvenli şekilde açar
    async with _lifespan(app):
        try:
            # MCP aracını doğrudan çağırarak tüm V2 süreçlerini (PageRank, Repo Map vb.) tetikletiyoruz.
            result = await index_project(project_path=project_path, collection=project_name, batch_size=batch_size)
            print("\n✨ İndeksleme Sonucu:")
            print(result)
        except Exception as e:
            print(f"\n❌ Hata oluştu: {e}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GraphMCP V2 Proje İndeksleyici (PageRank & Repo Map destekli)"
    )
    parser.add_argument("--project", required=True, help="Koleksiyon adı (örn: Vendoris)")
    parser.add_argument("--path",    required=True, help="Proje dizini (örn: /projects/Vendoris)")
    parser.add_argument("--batch",   type=int, default=32, help="Embedding batch boyutu (varsayılan: 32)")
    args = parser.parse_args()

    asyncio.run(run(args.project, args.path, args.batch))

if __name__ == "__main__":
    main()
