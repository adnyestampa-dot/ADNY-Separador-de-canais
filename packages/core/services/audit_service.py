from __future__ import annotations

import logging
import uuid
from typing import Any

from packages.infra.sqlite.database import Database

logger = logging.getLogger(__name__)


class AuditService:
    """Registra eventos do app para observabilidade e aprendizado da IA."""

    _instance: AuditService | None = None

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()
        self._session_id = str(uuid.uuid4())

    @classmethod
    def instance(cls) -> AuditService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def record(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        job_id: str | None = None,
    ) -> None:
        self._db.record_audit_event(
            session_id=self._session_id,
            event_type=event_type,
            payload=payload or {},
            job_id=job_id,
        )
        logger.debug("audit: %s %s", event_type, payload)
