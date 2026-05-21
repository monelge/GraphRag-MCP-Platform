import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.mcp.server import app, _lifespan
from src.mcp_server import execute_agent_task

async def test():
    async with _lifespan(app):
        print("🚀 Testing task steps persistence...")
        res = await execute_agent_task(
            goal="Test steps recording",
            project_path="/app",
            collection="GraphRagMCP"
        )
        print(res)

if __name__ == "__main__":
    asyncio.run(test())
