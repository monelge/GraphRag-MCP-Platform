from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server  # noqa: F401  # initialize MCP runtime before importing tools
from src.mcp.tool_registry import (
    analyze_change_impact,
    search_repo_architecture,
    summarize_repository,
)


async def run_demo(project_path: Path, collection: str, changed_file: str | None) -> None:
    print("=== Knowledge Plane Demo ===")
    print(f"Project: {project_path}")
    print(f"Collection: {collection}")
    print("")

    print("1) summarize_repository() çağrısı...")
    repo_summary = await summarize_repository(str(project_path), collection=collection)
    print(repo_summary[:2000])
    print("\n---\n")

    print("2) search_repo_architecture() çağrısı...")
    arch_result = await search_repo_architecture(
        "servis bağımlılıkları ve veri akışı",
        collection=collection,
        top_k=4,
    )
    print(arch_result[:2000])
    print("\n---\n")

    if changed_file:
        print("3) analyze_change_impact() çağrısı...")
        changed_path = [str(project_path / changed_file)]
        impact_result = await analyze_change_impact(
            str(project_path),
            changed_paths=changed_path,
            collection=collection,
        )
        print(impact_result[:2000])
        print("\n---\n")
    else:
        print("3) analyze_change_impact() atlandı. --changed-file argümanı verilmedi.")

    print("✅ Demo tamamlandı.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GraphRagMCP Knowledge Plane demo script."
    )
    parser.add_argument(
        "--project-path",
        default=str(ROOT),
        help="GraphRagMCP proje kökü. Varsayılan: repo kökü.",
    )
    parser.add_argument(
        "--collection",
        default="GraphRagMCP",
        help="Koleksiyon adı.",
    )
    parser.add_argument(
        "--changed-file",
        default="src/handlers/retrieval_handler.py",
        help="analyze_change_impact() için değişen dosya yolu, proje köküne göre.",
    )
    parser.add_argument(
        "--skip-impact",
        action="store_true",
        help="Etki analizini atla.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    changed_file = None if args.skip_impact else args.changed_file
    asyncio.run(run_demo(Path(args.project_path), args.collection, changed_file))


if __name__ == "__main__":
    main()
