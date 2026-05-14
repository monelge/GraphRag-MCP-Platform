"""Ontology node ve edge yazımı için Cypher sorgu üreticileri.

neo4j_store.upsert_nodes_and_relationships() tarafından kullanılır;
inline sorgu karmaşıklığını azaltır ve tip güvenliği sağlar.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.ontology.schema import EdgeType, NodeType


def build_upsert_query(
    source_label: str,
    target_label: str,
    rel_type: str,
) -> str:
    """
    İki node arasında MERGE + ilişki sorgusu üretir.
    neo4j_store'un name+collection primary key modeliyle uyumludur.
    """
    return (
        f"MERGE (s:{source_label} {{name: $s_name, collection: $coll}}) "
        f"SET s += $s_props "
        f"MERGE (t:{target_label} {{name: $t_name, collection: $coll}}) "
        f"SET t += $t_props "
        f"MERGE (s)-[:{rel_type}]->(t)"
    )


def build_node_query(node_type: NodeType, props: Dict[str, object]) -> Tuple[str, Dict[str, object]]:
    """Tek node MERGE sorgusunu ve parametrelerini üretir (node_id tabanlı)."""
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
