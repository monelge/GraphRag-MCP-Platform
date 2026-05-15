
import asyncio
import os
import sys
from src.handlers import AppContext
from src.mcp.server import _app_ctx, app
from src.storage.postgres_store import PostgresStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.redis_store import RedisStore

async def validate():
    print("--- GraphRagMCP V2 Validation ---")
    
    # Check Tools
    tools = list(app.tools.keys())
    print(f"Registered Tools ({len(tools)}): {', '.join(tools)}")
    
    expected_v2_tools = [
        "search_repo_architecture", 
        "analyze_change_impact", 
        "summarize_repository", 
        "search_decisions", 
        "store_decision_memory", 
        "run_verification_plan", 
        "resume_task"
    ]
    missing = [t for t in expected_v2_tools if t not in tools]
    if not missing:
        print("✅ All V2 tools are registered.")
    else:
        print(f"❌ Missing V2 tools: {missing}")

    # Check DB Connections
    print("\nChecking database connections...")
    
    try:
        await _app_ctx.postgres.connect()
        print("✅ PostgreSQL: Connected")
    except Exception as e:
        print(f"❌ PostgreSQL: Failed ({e})")

    try:
        await _app_ctx.neo4j.connect()
        print("✅ Neo4j: Connected")
    except Exception as e:
        print(f"❌ Neo4j: Failed ({e})")

    try:
        # Redis connection is lazy but we can test it
        await _app_ctx.redis.ping()
        print("✅ Redis: Connected")
    except Exception as e:
        print(f"❌ Redis: Failed ({e})")

    # Qdrant check (IndexingHandler uses it)
    try:
        from qdrant_client import QdrantClient
        qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        client = QdrantClient(url=qdrant_url)
        client.get_collections()
        print("✅ Qdrant: Connected")
    except Exception as e:
        print(f"❌ Qdrant: Failed ({e})")

    print("\n--- Validation Complete ---")

if __name__ == "__main__":
    asyncio.run(validate())
