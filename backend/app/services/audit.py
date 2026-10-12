"""Audit trail writer."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from app.observability import request_id_ctx

logger = logging.getLogger("app.services.audit")

#: Keys never written into the audit ``changes`` payload.
_SENSITIVE = frozenset({"password", "new_password", "current_password", "password_hash", "token"})


def scrub(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        key: ("[redacted]" if key.lower() in _SENSITIVE else value)
        for key, value in payload.items()
        if value is not None
    }


async def record(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    summary: str,
    actor: User | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
    actor_label: str | None = None,
) -> AuditLog:
    """Append an audit entry. Callers pass the same session so it commits with the change."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_label=actor_label or (actor.full_name if actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary,
        changes=scrub(changes),
        request_id=(request.state.request_id if request and hasattr(request.state, "request_id") else None)
        or request_id_ctx.get(),
    )
    session.add(entry)
    await session.flush()
    logger.info("audit %s %s %s", action, entity_type, entity_id or "-")
    return entry
