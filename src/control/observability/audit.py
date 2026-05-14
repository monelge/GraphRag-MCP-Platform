from __future__ import annotations

"""Audit event kayıtlarını PostgreSQL'e asenkron gönderen gözlemlenebilirlik katmanı."""

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.postgres_store import PostgresStore


class AuditLogger:
    """Fire-and-forget audit log yazımı için hafif sarmalayıcı."""

    RETRIEVAL_REQUEST = "retrieval_request"
    EXECUTION_COMMAND = "execution_command"
    APPROVAL_DECISION = "approval_decision"
    MEMORY_WRITE = "memory_write"
    INDEX_INVALIDATION = "index_invalidation"

    def __init__(self, pg: "PostgresStore" | None = None):
        self._pg = pg

    def set_postgres(self, pg: "PostgresStore") -> None:
        """Circular import oluşturmadan postgres store referansı bağlar."""
        self._pg = pg

    def log(
        self,
        event_type: str,
        collection: str = "",
        task_id: str = "",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Audit kaydını event loop üzerinde arka planda yazar."""
        if not self._pg:
            return
        asyncio.ensure_future(
            self._pg.log_audit_event(
                event_type=event_type,
                collection=collection,
                task_id=task_id,
                summary=summary,
                metadata=metadata or {},
            )
        )
