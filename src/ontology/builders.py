"""Ontology node ve edge yazımı için Cypher sorgu üreticileri."""

from __future__ import annotations

from typing import Dict, Tuple

from src.ontology.schema import EdgeType, NodeType


def build_node_query(node_type: NodeType, props: Dict[str, object]) -> Tuple[str, Dict[str, object]]:
    """Node MERGE sorgusunu ve parametrelerini üretir."""
    node_id = str(props.get("node_id") or props.get("id") or props.get("name") or "")
    query = (
        f"MERGE (n:{node_type.value} {{node_id: $node_id}}) "
        "SET n += $props "
        "RETURN n"
    )
    return query, {"node_id": node_id, "props": dict(props, node_id=node_id)}


def build_edge_query(
    edge_type: EdgeType,
    from_id: str,
    to_id: str,
    props: Dict[str, object],
) -> Tuple[str, Dict[str, object]]:
    """Edge MERGE sorgusunu ve parametrelerini üretir."""
    query = (
        "MATCH (a {node_id: $from_id}), (b {node_id: $to_id}) "
        f"MERGE (a)-[r:{edge_type.value}]->(b) "
        "SET r += $props "
        "RETURN r"
    )
    return query, {"from_id": from_id, "to_id": to_id, "props": props}
