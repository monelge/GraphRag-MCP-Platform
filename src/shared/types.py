"""Uygulama genelinde tekrar kullanılan ortak tip kısaltmaları."""

from __future__ import annotations

from typing import Any, Dict, NewType

JsonDict = Dict[str, Any]
CollectionName = NewType("CollectionName", str)
ProjectPath = NewType("ProjectPath", str)
CommitSha = NewType("CommitSha", str)
NodeId = NewType("NodeId", str)
