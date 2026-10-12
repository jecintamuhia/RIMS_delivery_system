"""Staff accounts and role-based access control.

Roles are a fixed three-level hierarchy (``viewer`` < ``editor`` < ``admin``). They are an
enumeration in code rather than a table because they gate code paths and must not be editable
at runtime; the *set* of users in each role is fully data-driven.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, ensure_utc, pk_column, string_enum


class Role(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def allows(self, required: Role) -> bool:
        """Hierarchical check: an admin satisfies an editor requirement."""
        return self.rank >= required.rank


_ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.EDITOR: 1, Role.ADMIN: 2}


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = pk_column()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        string_enum(Role, length=16), nullable=False, default=Role.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def is_locked(self, now: datetime) -> bool:
        """``locked_until`` is normalised on read: SQLite returns naive timestamps."""
        locked_until = ensure_utc(self.locked_until)
        return locked_until is not None and locked_until > ensure_utc(now)  # type: ignore[operator]

    @property
    def lock_expires_at(self) -> datetime | None:
        return ensure_utc(self.locked_until)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.email} role={self.role.value}>"
