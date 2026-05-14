from __future__ import annotations

"""Audit event kayıtlarını PostgreSQL'e asenkron gönderen gözlemlenebilirlik katmanı."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


class AuditLogger:
    """Audit log yazımı için hafif sarmalayıcı.

    STDIO transport'ta ensure_future güvenilir değildir (event loop yanıt sonrası
    kapanabilir). Bu nedenle log() async olarak tanımlandı — caller tarafından await edilir.
    """

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

    async def log(
        self,
        event_type: str,
        collection: str = "",
        task_id: str = "",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Audit kaydını doğrudan await ederek yazar; STDIO transport ile uyumlu."""
        if not self._pg:
            return
        try:
            await self._pg.log_audit_event(
                event_type=event_type,
                collection=collection,
                task_id=task_id,
                summary=summary,
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.debug("audit log yazılamadı: %s", exc)
