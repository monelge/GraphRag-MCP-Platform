import asyncio, sys
sys.path.insert(0, '/app')
from src.mcp_server import index_project

async def main():
    result = await index_project('/projects/WareLogisticcBYS', collection='WareLogisticcBYS')
    print(result)

asyncio.run(main())
