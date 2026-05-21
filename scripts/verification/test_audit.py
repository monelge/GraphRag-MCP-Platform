import asyncio
import sys
from pathlib import Path
sys.path.append("/app")

from src.storage.postgres_store import PostgresStore
from src.shared.config import config

async def test():
    pg = PostgresStore()
    await pg.connect()
    if pg.available:
        print("PG connected")
        await pg.log_audit_event("manual_test", collection="test", summary="direct write script")
        print("Log sent")
    else:
        print("PG not available")
    await pg.close()

if __name__ == "__main__":
    asyncio.run(test())
