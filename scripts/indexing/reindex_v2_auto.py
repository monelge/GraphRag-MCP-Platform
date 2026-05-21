import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.qdrant_store import QdrantStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.redis_store import RedisStore
from src.storage.postgres_store import PostgresStore
from src.shared.project_registry import ProjectRegistry
from src.indexing.pipelines.project_intelligence import sync_project_intelligence

# Import the reindex logic by running it as a module or importing functions
# Since reindex.py is designed as a script, we'll call its main run function if possible
# or just re-implement the call.
import scripts.reindex as reindex_script

PROJECTS = [
    {"name": "Vendoris", "path": "/projects/Vendoris"},
    {"name": "WareLogisticcBYS", "path": "/projects/WareLogisticcBYS"}
]

async def full_reset_and_reindex():
    print("🚀 GraphRagMCP v2 - Full Re-indexing Process Starting...")
    
    # 1. CLEANUP
    print("\n--- [1/3] Cleaning Databases ---")
    
    # Neo4j
    neo4j = Neo4jStore()
    await neo4j.connect()
    await neo4j.query("MATCH (n) DETACH DELETE n")
    print("✅ Neo4j: All nodes and relationships deleted.")
    
    # Redis
    redis = RedisStore()
    if redis.available:
        await redis._client.flushall()
        print("✅ Redis: Cache cleared.")
    else:
        print("ℹ Redis: Not available, skipping cache clear.")
    
    # Qdrant
    qdrant = QdrantStore()
    for proj in PROJECTS:
        coll = proj["name"]
        if await qdrant.client.collection_exists(coll):
            await qdrant.client.delete_collection(coll)
            print(f"✅ Qdrant: Collection '{coll}' deleted.")
            
    # Project Registry
    registry_path = Path("/app/data/graphmcp/project_registry.json")
    if registry_path.exists():
        registry_path.unlink()
        print("✅ Project Registry: Reset.")
    
    # 2. REGISTER & INTELLIGENCE (V2)
    print("\n--- [2/3] Registering Projects & Syncing Intelligence (v2) ---")
    for proj in PROJECTS:
        print(f"📡 Syncing {proj['name']}...")
        profile = await sync_project_intelligence(
            project_path=proj["path"],
            collection=proj["name"],
            redis_store=redis,
            neo4j_store=neo4j
        )
        print(f"✅ {proj['name']} Registered. (Summary & Architecture Index Created)")

    # 3. FULL INDEXING
    print("\n--- [3/3] Full Code Indexing (AST, Graph, Vector) ---")
    for proj in PROJECTS:
        print(f"🔍 Indexing {proj['name']} at {proj['path']}...")
        await reindex_script.run(
            project_name=proj["name"],
            project_path=proj["path"],
            batch_size=32,
            yes=True  # Skip confirmation
        )
    
    print("\n✨ ALL PROCESSES COMPLETED SUCCESSFULLY!")
    print(f"Projects indexed: {[p['name'] for p in PROJECTS]}")
    
    await neo4j.close()
    await redis.close()

if __name__ == "__main__":
    asyncio.run(full_reset_and_reindex())
