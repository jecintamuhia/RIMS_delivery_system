"""Audit trail.

Every administrative mutation writes an :class:`AuditLog` row. Entries are append-only and
store a human-readable summary, because the point is to answer "who changed this price and
when" long after the fact. Request payloads are intentionally not stored wholesale - a summary
plus the changed fields is enough and avoids copying customer data into the log store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pk_column


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = pk_column()
    actor_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Denormalised so the entry stays readable after a user is deleted.
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_audit_entity_recent", "entity_type", "entity_id", "created_at"),)


class SystemSetting(Base):
    """Key/value configuration editable by an administrator.

    Secrets never live here - they come from the environment. This holds operational
    settings such as the dispatch point, contact details and the active pricing version.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
