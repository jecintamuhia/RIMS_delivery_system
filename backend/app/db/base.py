"""SQLAlchemy declarative base, naming conventions and portable column types.

Alembic autogenerate relies on the naming conventions below, so every index and constraint
name is deterministic and safe to reference from a migration.
"""

from __future__ import annotations

import enum as _enum
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


#: Money is stored to the cent. ``Decimal`` everywhere - never float - so the pricing engine
#: can add a base price and adjustments without rounding drift.
Money = Numeric(12, 2)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def pk_column() -> Mapped[str]:
    """Public opaque identifier. UUID4 hex so ids are not guessable or enumerable."""
    from uuid import uuid4

    return mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)


def fk(target: str, *, nullable: bool = False, ondelete: str = "RESTRICT", index: bool = True) -> Mapped[str]:
    return mapped_column(
        String(32),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def money_column(*, nullable: bool = False) -> Mapped[Decimal]:
    return mapped_column(Money, nullable=nullable)


def string_enum(enum_cls: type[_enum.Enum], *, length: int = 32) -> SAEnum:
    """A non-native enum column that stores the enum's *values*, not its member names.

    SQLAlchemy's default is to persist the Python member name, which would write ``"NONE"``
    for ``AdjustmentType.NONE``. Every value in these enums is also a wire-format string
    (``"none"``, ``"needs_review"``, ``"viewer"``) that the API, the database check constraints
    and the frontend all compare literally, so the column must store the value verbatim.
    ``values_callable`` is what guarantees that.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


def ensure_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime read back from storage to timezone-aware UTC.

    SQLite has no native timestamp type and returns naive datetimes even for
    ``DateTime(timezone=True)``, so a value written as aware comes back naive. Comparing that
    with an aware ``now()`` raises ``TypeError``, which would surface as a 500 on an
    authentication or expiry path. Normalising on read keeps those comparisons sound on both
    SQLite and PostgreSQL.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "Money",
    "TimestampMixin",
    "ensure_utc",
    "fk",
    "money_column",
    "pk_column",
    "string_enum",
]
