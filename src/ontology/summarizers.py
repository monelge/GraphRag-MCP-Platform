"""Ontology node'larından özet metin üreten yardımcılar."""

from __future__ import annotations

from typing import Dict

from src.ontology.schema import NodeType


def node_to_summary_text(node_type: NodeType, props: Dict[str, object]) -> str:
    """Node tipine göre kısa özet metni üretir."""
    name = str(props.get("name") or props.get("node_id") or "isimsiz")
    file_path = str(props.get("file_path") or "")
    purpose = str(props.get("purpose") or props.get("summary") or "")
    parts = [f"{node_type.value}: {name}"]
    if file_path:
        parts.append(f"Dosya: {file_path}")
    if purpose:
        parts.append(f"Özet: {purpose}")
    return " | ".join(parts)
