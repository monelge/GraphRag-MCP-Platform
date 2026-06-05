#!/usr/bin/env python3
import sys
import os
import argparse
import asyncio

# ONNX and TF noise suppression
os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Ensure runtime directory is in sys.path
sys.path.append(os.getcwd())

from src.mcp.server import _redis, _postgres, _neo4j
from src.mcp_server import search_code, explain_code, search_agent_docs

async def main():
    parser = argparse.ArgumentParser(description="GraphMCP Semantic Search CLI Runner")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--collection", "-c", default="Vendoris", help="Indexed collection name (e.g. Vendoris)")
    parser.add_argument("--type", "-t", default="code", choices=["code", "explain", "doc"], help="Search tool mode")
    
    args = parser.parse_args()
    
    # Initialize necessary asynchronous connections
    await _redis.connect()
    await _postgres.connect()
    await _neo4j.connect()
    
    try:
        if args.type == "code":
            res = await search_code(args.query, collection=args.collection)
        elif args.type == "explain":
            res = await explain_code(args.query, collection=args.collection)
        elif args.type == "doc":
            res = await search_agent_docs(args.query, collection=args.collection)
        else:
            res = "❌ Unknown search type"
            
        print(res)
    except Exception as e:
        print(f"❌ Error occurred during semantic search: {e}", file=sys.stderr)
    finally:
        # Safely release resource pools
        await _redis.close()
        await _postgres.close()
        await _neo4j.close()

if __name__ == "__main__":
    asyncio.run(main())
