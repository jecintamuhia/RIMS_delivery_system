"""Shared helpers for the admin routers.

Conflict detection and audit-summary formatting live here so every admin endpoint reports
validation problems the same way, and every mutation is auditable without repeating boilerplate.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ErrorCode
from app.models import (
    DeliveryZone,
    Destination,
    DestinationAlias,
    DynamicPricingVersion,
    PricingVersion,
    RoadType,
    User,
    VehicleCategory,
)
from app.services.audit import record
from app.services.geo import normalise_place_name

T = TypeVar("T")

#: label -> (model, field) used for human-readable duplicate-code errors. Only fields a human
#: actually supplies are checked here; ``scope_key`` and generated ids are enforced by the
#: database instead, and duplicating those checks in application code would only drift.
UNIQUE_MODELS: dict[str, tuple[type[Any], str]] = {
    "destination": (Destination, "code"),
    "delivery_zone": (DeliveryZone, "code"),
    "road_type": (RoadType, "code"),
    "vehicle": (VehicleCategory, "code"),
    "pricing_version": (PricingVersion, "label"),
    "dynamic_pricing_version": (DynamicPricingVersion, "label"),
    "user": (User, "email"),
}


async def ensure_unique(
    session: AsyncSession,
    entity: str,
    field: str,
    value: str,
    *,
    exclude_id: str | None = None,
) -> None:
    """Reject a duplicate code/name/alias with a message an admin can act on."""
    model, attribute = UNIQUE_MODELS[entity]
    column = getattr(model, attribute)
    stmt = select(model.id).where(column == value)
    if exclude_id:
        stmt = stmt.where(model.id != exclude_id)
    if await session.scalar(stmt):
        raise AppError(
            ErrorCode.VALIDATION,
            f"A {entity.replace('_', ' ')} with {field} “{value}” already exists.",
            details={"field": field, "value": value},
        )


async def ensure_alias_available(
    session: AsyncSession, alias: str, *, exclude_destination_id: str | None = None
) -> None:
    """An alias must be unique across all destinations.

    ``destination_aliases`` has a per-destination unique index, but an alias resolving to two
    different destinations would make destination resolution ambiguous - which destination does
    "Kisumu" mean? - so it is rejected here. Comparison is on the normalised form so
    "Kisumu Town" and "kisumu-town" are treated as the same alias.
    """
    normalised = normalise_place_name(alias)
    if not normalised:
        raise AppError(ErrorCode.VALIDATION, "Alias cannot be empty.", details={"field": "alias"})

    rows = (
        await session.execute(
            select(DestinationAlias.destination_id, DestinationAlias.alias)
            .join(Destination, Destination.id == DestinationAlias.destination_id)
            .where(DestinationAlias.is_active.is_(True))
        )
    ).all()
    for destination_id, existing in rows:
        if normalise_place_name(existing) == normalised and destination_id != exclude_destination_id:
            destination = await session.get(Destination, destination_id)
            raise AppError(
                ErrorCode.VALIDATION,
                f"Alias “{alias}” is already used by destination "
                f"“{destination.name if destination else destination_id}”.",
                details={"field": "alias", "value": alias},
            )


async def audit(
    session: AsyncSession,
    request: Request,
    *,
    action: str,
    entity_type: str,
    summary: str,
    entity_id: str | None = None,
    entity_label: str | None = None,
    changes: dict[str, Any] | None = None,
    actor: User | None = None,
) -> None:
    await record(
        session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary,
        changes=changes,
        actor=actor,
        request=request,
    )


def diff_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Only the fields that actually changed, for the audit entry."""
    return {
        key: {"from": before.get(key), "to": value}
        for key, value in after.items()
        if before.get(key) != value
    }


def translate_integrity_error(exc: IntegrityError) -> AppError:
    """Turn a database constraint violation into a validation error, not a 500."""
    detail = str(getattr(exc, "orig", exc))
    lowered = detail.lower()
    if "unique" in lowered:
        return AppError(ErrorCode.VALIDATION, "That value is already in use.")
    if "foreign key" in lowered or "violates foreign key" in lowered:
        return AppError(
            ErrorCode.VALIDATION,
            "That change would reference something that does not exist, or is still in use.",
        )
    if "check" in lowered or "constraint" in lowered:
        return AppError(ErrorCode.VALIDATION, "That combination of values is not allowed.")
    return AppError(ErrorCode.SERVER)
