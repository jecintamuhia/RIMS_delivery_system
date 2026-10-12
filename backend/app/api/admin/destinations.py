"""Destinations, zones and aliases.

A destination is the thing RIMs quotes to. Everything else in the pricing model hangs off it, so
these endpoints are where an operator builds the geography that later makes automatic matching
possible. Deactivation (``active: false``) is preferred over deletion: an existing quote may
already reference the row, and the audit trail has to stay readable.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.admin_common import audit, ensure_alias_available, ensure_unique
from app.api.admin_schemas import (
    AliasInput,
    DestinationInput,
    DestinationModel,
    DestinationUpdate,
    LatLngOut,
    MoneyOut,
    ZoneInput,
    ZoneModel,
    ZoneUpdate,
)
from app.api.deps import (
    EditorWriter,
    PaginationDep,
    RequireViewer,
    SessionDep,
    build_page,
)
from app.errors import AppError, ErrorCode, not_found
from app.models import (
    DeliveryZone,
    Destination,
    DestinationAlias,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
)

logger = logging.getLogger("app.api.admin.destinations")

router = APIRouter(prefix="/admin", tags=["admin"])


def _current_price_subquery() -> Select[Decimal]:
    """The base price a destination currently quotes under the active pricing version."""
    return (
        select(PricingRule.base_price)
        .join(PricingVersion, PricingVersion.id == PricingRule.version_id)
        .where(
            PricingRule.destination_id == Destination.id,
            PricingRule.road_type_id.is_(None),
            PricingRule.vehicle_id.is_(None),
            PricingRule.is_active.is_(True),
            PricingVersion.status == PricingVersionStatus.ACTIVE,
        )
        .order_by(PricingRule.priority.desc())
        .limit(1)
    )


async def _load(session: SessionDep, destination_id: str) -> Destination:
    destination = await session.scalar(
        select(Destination)
        .where(Destination.id == destination_id)
        .options(selectinload(Destination.aliases), selectinload(Destination.zone))
    )
    if destination is None:
        raise not_found("Destination", destination_id)
    return destination


async def _serialise(session: SessionDep, destination: Destination) -> DestinationModel:
    """Attach the destination's current price, read from the active version only.

    Only the unqualified rule (no road-type, no vehicle) counts as "the price of this
    destination"; showing a qualified surcharge as the headline figure would misreport it.
    """
    price = await session.scalar(_current_price_subquery().where(Destination.id == destination.id))
    return DestinationModel(
        id=destination.id,
        name=destination.name,
        code=destination.code,
        zone=destination.zone.name if destination.zone else "",
        zoneId=destination.zone_id,
        county=destination.county,
        position=(
            LatLngOut(lat=destination.latitude, lng=destination.longitude)
            if destination.latitude is not None and destination.longitude is not None
            else None
        ),
        active=destination.is_active,
        aliases=[alias.alias for alias in destination.aliases],
        aliasesCount=len(destination.aliases),
        hasBoundary=destination.boundary is not None,
        catchmentRadiusKm=destination.catchment_radius_km,
        currentBasePrice=(
            MoneyOut(amount=price, currency="KES") if price is not None else None
        ),
    )


# ── destinations ─────────────────────────────────────────────────────────────────────


@router.get("/destinations", response_model=dict[str, Any], summary="List destinations")
async def list_destinations(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    search: Annotated[str | None, Query(max_length=160)] = None,
    zoneId: Annotated[str | None, Query(max_length=32)] = None,
    active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Destination.name.ilike(pattern),
                Destination.code.ilike(pattern),
                Destination.county.ilike(pattern),
            )
        )
    if zoneId:
        conditions.append(Destination.zone_id == zoneId)
    if active is not None:
        conditions.append(Destination.is_active.is_(active))

    total = int(
        await session.scalar(select(func.count(Destination.id)).where(*conditions)) or 0
    )
    rows = (
        await session.scalars(
            select(Destination)
            .where(*conditions)
            .options(selectinload(Destination.aliases), selectinload(Destination.zone))
            .order_by(Destination.name)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    items = [await _serialise(session, row) for row in rows]
    return build_page(items, total, page)


@router.get("/destinations/{destination_id}", response_model=DestinationModel, summary="Read a destination")
async def get_destination(destination_id: str, session: SessionDep, _: RequireViewer) -> DestinationModel:
    return await _serialise(session, await _load(session, destination_id))


@router.post(
    "/destinations",
    response_model=DestinationModel,
    status_code=201,
    summary="Create a destination",
)
async def create_destination(
    payload: DestinationInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> DestinationModel:
    await ensure_unique(session, "destination", "code", payload.code)
    if payload.zoneId:
        await _require_zone(session, payload.zoneId)

    destination = Destination(
        name=payload.name,
        code=payload.code,
        zone_id=payload.zoneId,
        county=payload.county,
        latitude=payload.lat,
        longitude=payload.lng,
        boundary=payload.boundary,
        catchment_radius_km=payload.catchmentRadiusKm,
        is_active=payload.active,
    )
    session.add(destination)
    await session.flush()

    for alias in _clean_aliases(payload.aliases):
        await ensure_alias_available(session, alias, exclude_destination_id=destination.id)
        session.add(DestinationAlias(destination_id=destination.id, alias=alias))
    await session.flush()

    await audit(
        session,
        request,
        action="created",
        entity_type="destination",
        entity_id=destination.id,
        entity_label=destination.name,
        summary=f"Created destination “{destination.name}” ({destination.code})",
        actor=actor.user,
    )
    await session.commit()
    logger.info("destination created %s", destination.id)
    return await _serialise(session, await _load(session, destination.id))


@router.patch("/destinations/{destination_id}", response_model=DestinationModel, summary="Update a destination")
async def update_destination(
    destination_id: str,
    payload: DestinationUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> DestinationModel:
    destination = await _load(session, destination_id)
    before = {
        "name": destination.name,
        "code": destination.code,
        "zoneId": destination.zone_id,
        "county": destination.county,
        "active": destination.is_active,
        "catchmentRadiusKm": destination.catchment_radius_km,
    }

    if payload.code and payload.code != destination.code:
        await ensure_unique(session, "destination", "code", payload.code, exclude_id=destination.id)
        destination.code = payload.code
    if payload.zoneId:
        await _require_zone(session, payload.zoneId)
    for field in ("name", "zoneId", "county", "lat", "lng", "boundary", "active", "catchmentRadiusKm"):
        value = getattr(payload, field, None)
        if value is None:
            continue
        if field == "zoneId":
            destination.zone_id = value
        elif field == "lat":
            destination.latitude = value
        elif field == "lng":
            destination.longitude = value
        elif field == "catchmentRadiusKm":
            destination.catchment_radius_km = value
        else:
            setattr(destination, field, value)

    if payload.aliases is not None:
        await _replace_aliases(session, destination, payload.aliases)

    after = {
        "name": destination.name,
        "code": destination.code,
        "zoneId": destination.zone_id,
        "county": destination.county,
        "active": destination.is_active,
        "catchmentRadiusKm": destination.catchment_radius_km,
    }
    await audit(
        session,
        request,
        action="updated",
        entity_type="destination",
        entity_id=destination.id,
        entity_label=destination.name,
        summary=f"Updated destination “{destination.name}”",
        changes={"fields": {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}},
        actor=actor.user,
    )
    await session.commit()
    return await _serialise(session, await _load(session, destination.id))


@router.post(
    "/destinations/{destination_id}/aliases",
    response_model=DestinationModel,
    status_code=201,
    summary="Add a destination alias",
)
async def add_alias(
    destination_id: str,
    payload: AliasInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> DestinationModel:
    """Aliases are how a geocoder's spelling is mapped to a configured destination."""
    destination = await _load(session, destination_id)
    alias = payload.alias.strip()
    await ensure_alias_available(session, alias, exclude_destination_id=destination.id)
    existing = await session.scalar(
        select(DestinationAlias).where(
            DestinationAlias.destination_id == destination.id, DestinationAlias.alias == alias
        )
    )
    if existing is None:
        session.add(DestinationAlias(destination_id=destination.id, alias=alias))
    else:
        existing.is_active = True
    await audit(
        session,
        request,
        action="alias_added",
        entity_type="destination",
        entity_id=destination.id,
        entity_label=destination.name,
        summary=f"Added alias “{alias}” to “{destination.name}”",
        actor=actor.user,
    )
    await session.commit()
    return await _serialise(session, await _load(session, destination.id))


@router.delete("/destinations/{destination_id}/aliases/{alias_id}", status_code=204, summary="Remove an alias")
async def remove_alias(
    destination_id: str,
    alias_id: str,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> None:
    alias = await session.scalar(
        select(DestinationAlias).where(
            DestinationAlias.id == alias_id, DestinationAlias.destination_id == destination_id
        )
    )
    if alias is None:
        raise not_found("Alias", alias_id)
    label = alias.alias
    await session.delete(alias)
    await audit(
        session,
        request,
        action="alias_removed",
        entity_type="destination",
        entity_id=destination_id,
        summary=f"Removed alias “{label}”",
        actor=actor.user,
    )
    await session.commit()


# ── zones ─────────────────────────────────────────────────────────────────────────────


@router.get("/zones", response_model=list[ZoneModel], summary="List delivery zones")
async def list_zones(session: SessionDep, _: RequireViewer, active: bool | None = None) -> list[ZoneModel]:
    conditions = [DeliveryZone.is_active.is_(True)] if active else []
    zones = (
        await session.scalars(
            select(DeliveryZone).where(*conditions).order_by(DeliveryZone.name)
        )
    ).all()
    counts = dict(
        (
            await session.execute(
                select(Destination.zone_id, func.count(Destination.id)).group_by(Destination.zone_id)
            )
        ).all()
    )
    return [
        ZoneModel(
            id=zone.id,
            name=zone.name,
            code=zone.code,
            description=zone.description,
            active=zone.is_active,
            destinationCount=int(counts.get(zone.id, 0)),
        )
        for zone in zones
    ]


@router.post("/zones", response_model=ZoneModel, status_code=201, summary="Create a delivery zone")
async def create_zone(
    payload: ZoneInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> ZoneModel:
    await ensure_unique(session, "delivery_zone", "code", payload.code)
    zone = DeliveryZone(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        is_active=payload.active,
    )
    session.add(zone)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="zone",
        entity_id=zone.id,
        entity_label=zone.name,
        summary=f"Created zone “{zone.name}”",
        actor=actor.user,
    )
    await session.commit()
    return ZoneModel(
        id=zone.id,
        name=zone.name,
        code=zone.code,
        description=zone.description,
        active=zone.is_active,
        destinationCount=0,
    )


@router.patch("/zones/{zone_id}", response_model=ZoneModel, summary="Update a delivery zone")
async def update_zone(
    zone_id: str,
    payload: ZoneUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> ZoneModel:
    zone = await session.get(DeliveryZone, zone_id)
    if zone is None:
        raise not_found("Zone", zone_id)
    if payload.code and payload.code != zone.code:
        await ensure_unique(session, "delivery_zone", "code", payload.code, exclude_id=zone.id)
        zone.code = payload.code
    if payload.name is not None:
        zone.name = payload.name
    if payload.description is not None:
        zone.description = payload.description
    if payload.active is not None:
        zone.is_active = payload.active
    await audit(
        session,
        request,
        action="updated",
        entity_type="zone",
        entity_id=zone.id,
        entity_label=zone.name,
        summary=f"Updated zone “{zone.name}”",
        actor=actor.user,
    )
    await session.commit()
    count = int(
        await session.scalar(
            select(func.count(Destination.id)).where(Destination.zone_id == zone.id)
        )
        or 0
    )
    return ZoneModel(
        id=zone.id,
        name=zone.name,
        code=zone.code,
        description=zone.description,
        active=zone.is_active,
        destinationCount=count,
    )


# ── helpers ───────────────────────────────────────────────────────────────────────────


def _clean_aliases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        alias = value.strip()
        if alias and alias.casefold() not in seen:
            seen.add(alias.casefold())
            out.append(alias)
    return out


async def _require_zone(session: SessionDep, zone_id: str) -> DeliveryZone:
    zone = await session.get(DeliveryZone, zone_id)
    if zone is None:
        raise AppError(
            ErrorCode.VALIDATION,
            f"Zone {zone_id} does not exist.",
            details={"field": "zoneId"},
        )
    return zone


async def _replace_aliases(session: SessionDep, destination: Destination, aliases: list[str]) -> None:
    """Make the stored alias set exactly match what was submitted."""
    wanted = _clean_aliases(aliases)
    for alias in wanted:
        await ensure_alias_available(session, alias, exclude_destination_id=destination.id)
    current = {row.alias: row for row in destination.aliases}
    for alias, row in current.items():
        if alias not in wanted:
            await session.delete(row)
    for alias in wanted:
        if alias not in current:
            session.add(DestinationAlias(destination_id=destination.id, alias=alias))
    await session.flush()
