"""Reference data: road types, road segments, vehicle categories and delivery origins.

These are the inputs to classification. Road segments are matched by an explicit radius around a
representative point, and only *confirmed* segments are used - an unconfirmed classification is
RIMs' draft, not RIMs' decision, and quoting from it would be pricing on an assumption.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.admin_common import audit, ensure_unique
from app.api.admin_schemas import (
    LatLngOut,
    OriginInput,
    OriginModel,
    OriginUpdate,
    RoadSegmentInput,
    RoadSegmentModel,
    RoadSegmentUpdate,
    RoadTypeInput,
    RoadTypeUpdate,
    VehicleInput,
    VehicleUpdate,
)
from app.api.deps import EditorWriter, PaginationDep, RequireViewer, SessionDep, build_page
from app.api.schemas import RoadTypeModel, VehicleCategoryModel
from app.api.serializers import road_type_model, vehicle_model
from app.errors import AppError, ErrorCode, not_found
from app.models import (
    DeliveryOrigin,
    Destination,
    RoadCondition,
    RoadSegment,
    RoadType,
    VehicleCategory,
)

logger = logging.getLogger("app.api.admin.reference")

router = APIRouter(prefix="/admin", tags=["admin"])


# ── road types ────────────────────────────────────────────────────────────────────────


@router.get("/road-types", response_model=dict[str, Any], summary="List road types")
async def list_road_types(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    conditions = [RoadType.is_active.is_(active)] if active is not None else []
    total = int(await session.scalar(select(func.count(RoadType.id)).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            select(RoadType)
            .where(*conditions)
            .order_by(RoadType.name)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    return build_page([road_type_model(row) for row in rows], total, page)


@router.get("/road-types/{road_type_id}", response_model=RoadTypeModel, summary="Read a road type")
async def get_road_type(road_type_id: str, session: SessionDep, _: RequireViewer) -> RoadTypeModel:
    road_type = await session.get(RoadType, road_type_id)
    if road_type is None:
        raise not_found("Road type", road_type_id)
    return road_type_model(road_type)


@router.post("/road-types", response_model=RoadTypeModel, status_code=201, summary="Create a road type")
async def create_road_type(
    payload: RoadTypeInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> RoadTypeModel:
    await ensure_unique(session, "road_type", "code", payload.code)
    existing_name = await session.scalar(select(RoadType.id).where(RoadType.name == payload.name))
    if existing_name:
        raise AppError(
            ErrorCode.VALIDATION, f"A road type named “{payload.name}” already exists.", details={"field": "name"}
        )
    road_type = RoadType(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        condition=RoadCondition(payload.condition),
        is_active=payload.active,
    )
    session.add(road_type)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="road_type",
        entity_id=road_type.id,
        entity_label=road_type.name,
        summary=f"Created road type “{road_type.name}”",
        actor=actor.user,
    )
    await session.commit()
    return road_type_model(road_type)


@router.patch("/road-types/{road_type_id}", response_model=RoadTypeModel, summary="Update a road type")
async def update_road_type(
    road_type_id: str,
    payload: RoadTypeUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> RoadTypeModel:
    road_type = await session.get(RoadType, road_type_id)
    if road_type is None:
        raise not_found("Road type", road_type_id)
    if payload.code and payload.code != road_type.code:
        await ensure_unique(session, "road_type", "code", payload.code, exclude_id=road_type.id)
        road_type.code = payload.code
    if payload.name is not None:
        road_type.name = payload.name
    if payload.description is not None:
        road_type.description = payload.description
    if payload.condition is not None:
        road_type.condition = RoadCondition(payload.condition)
    if payload.active is not None:
        road_type.is_active = payload.active
    await audit(
        session,
        request,
        action="updated",
        entity_type="road_type",
        entity_id=road_type.id,
        entity_label=road_type.name,
        summary=f"Updated road type “{road_type.name}”",
        actor=actor.user,
    )
    await session.commit()
    return road_type_model(road_type)


# ── vehicles ──────────────────────────────────────────────────────────────────────────


@router.get("/vehicles", response_model=dict[str, Any], summary="List vehicle categories")
async def list_vehicles(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    conditions = [VehicleCategory.is_active.is_(active)] if active is not None else []
    total = int(await session.scalar(select(func.count(VehicleCategory.id)).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            select(VehicleCategory)
            .where(*conditions)
            .order_by(VehicleCategory.sort_order, VehicleCategory.name)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    return build_page([vehicle_model(row) for row in rows], total, page)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleCategoryModel, summary="Read a vehicle category")
async def get_vehicle(vehicle_id: str, session: SessionDep, _: RequireViewer) -> VehicleCategoryModel:
    vehicle = await session.get(VehicleCategory, vehicle_id)
    if vehicle is None:
        raise not_found("Vehicle category", vehicle_id)
    return vehicle_model(vehicle)


@router.post("/vehicles", response_model=VehicleCategoryModel, status_code=201, summary="Create a vehicle category")
async def create_vehicle(
    payload: VehicleInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> VehicleCategoryModel:
    await ensure_unique(session, "vehicle", "code", payload.code)
    vehicle = VehicleCategory(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        max_weight_kg=payload.maxWeightKg,
        max_volume_m3=payload.maxVolumeM3,
        sort_order=payload.sortOrder,
        is_active=payload.active,
    )
    session.add(vehicle)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="vehicle",
        entity_id=vehicle.id,
        entity_label=vehicle.name,
        summary=f"Created vehicle category “{vehicle.name}”",
        actor=actor.user,
    )
    await session.commit()
    return vehicle_model(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleCategoryModel, summary="Update a vehicle category")
async def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> VehicleCategoryModel:
    vehicle = await session.get(VehicleCategory, vehicle_id)
    if vehicle is None:
        raise not_found("Vehicle category", vehicle_id)
    for field, column in (
        ("name", "name"),
        ("description", "description"),
        ("maxWeightKg", "max_weight_kg"),
        ("maxVolumeM3", "max_volume_m3"),
        ("sortOrder", "sort_order"),
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(vehicle, column, value)
    if payload.code and payload.code != vehicle.code:
        await ensure_unique(session, "vehicle", "code", payload.code, exclude_id=vehicle.id)
        vehicle.code = payload.code
    if payload.active is not None:
        vehicle.is_active = payload.active
    await audit(
        session,
        request,
        action="updated",
        entity_type="vehicle",
        entity_id=vehicle.id,
        entity_label=vehicle.name,
        summary=f"Updated vehicle category “{vehicle.name}”",
        actor=actor.user,
    )
    await session.commit()
    return vehicle_model(vehicle)


# ── road segments ─────────────────────────────────────────────────────────────────────


@router.get("/road-segments", response_model=dict[str, Any], summary="List classified road segments")
async def list_road_segments(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    roadTypeId: Annotated[str | None, Query(max_length=32)] = None,
    destinationId: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    conditions = []
    if roadTypeId:
        conditions.append(RoadSegment.road_type_id == roadTypeId)
    if destinationId:
        conditions.append(RoadSegment.destination_id == destinationId)
    total = int(await session.scalar(select(func.count(RoadSegment.id)).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            select(RoadSegment)
            .where(*conditions)
            .options(selectinload(RoadSegment.road_type))
            .order_by(RoadSegment.name)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    return build_page([_segment_out(row) for row in rows], total, page)


@router.post("/road-segments", response_model=RoadSegmentModel, status_code=201, summary="Classify a road segment")
async def create_road_segment(
    payload: RoadSegmentInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> RoadSegmentModel:
    if await session.get(RoadType, payload.roadTypeId) is None:
        raise AppError(
            ErrorCode.VALIDATION, "That road type does not exist.", details={"field": "roadTypeId"}
        )
    if payload.destinationId and await session.get(Destination, payload.destinationId) is None:
        raise AppError(
            ErrorCode.VALIDATION, "That destination does not exist.", details={"field": "destinationId"}
        )
    segment = RoadSegment(
        name=payload.name,
        road_type_id=payload.roadTypeId,
        destination_id=payload.destinationId,
        latitude=payload.lat,
        longitude=payload.lng,
        radius_km=payload.radiusKm,
        is_confirmed=payload.confirmed,
        is_active=payload.active,
    )
    session.add(segment)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="road_segment",
        entity_id=segment.id,
        entity_label=segment.name,
        summary=(
            f"Classified “{segment.name}” within {segment.radius_km} km"
            + ("" if segment.is_confirmed else " (unconfirmed, not used for pricing)")
        ),
        actor=actor.user,
    )
    await session.commit()
    await session.refresh(segment, attribute_names=["id"])
    return _segment_out(await _load_segment(session, segment.id))


@router.patch("/road-segments/{segment_id}", response_model=RoadSegmentModel, summary="Update a road segment")
async def update_road_segment(
    segment_id: str,
    payload: RoadSegmentUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> RoadSegmentModel:
    segment = await _load_segment(session, segment_id)
    for field, column in (
        ("name", "name"),
        ("roadTypeId", "road_type_id"),
        ("destinationId", "destination_id"),
        ("lat", "latitude"),
        ("lng", "longitude"),
        ("radiusKm", "radius_km"),
        ("confirmed", "is_confirmed"),
        ("active", "is_active"),
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(segment, column, value)
    await audit(
        session,
        request,
        action="updated",
        entity_type="road_segment",
        entity_id=segment.id,
        entity_label=segment.name,
        summary=f"Updated road segment “{segment.name}”",
        actor=actor.user,
    )
    await session.commit()
    return _segment_out(await _load_segment(session, segment.id))


async def _load_segment(session: SessionDep, segment_id: str) -> RoadSegment:
    segment = await session.scalar(
        select(RoadSegment)
        .where(RoadSegment.id == segment_id)
        .options(selectinload(RoadSegment.road_type))
    )
    if segment is None:
        raise not_found("Road segment", segment_id)
    return segment


def _segment_out(segment: RoadSegment) -> RoadSegmentModel:
    return RoadSegmentModel(
        id=segment.id,
        name=segment.name,
        roadTypeId=segment.road_type_id,
        roadTypeName=segment.road_type.name if segment.road_type else None,
        destinationId=segment.destination_id,
        position=LatLngOut(lat=segment.latitude, lng=segment.longitude),
        radiusKm=Decimal(segment.radius_km),
        confirmed=segment.is_confirmed,
        active=segment.is_active,
    )


# ── delivery origins ──────────────────────────────────────────────────────────────────


@router.get("/origins", response_model=list[OriginModel], summary="List delivery origins")
async def list_origins(session: SessionDep, _: RequireViewer) -> list[OriginModel]:
    origins = (
        await session.scalars(select(DeliveryOrigin).order_by(DeliveryOrigin.is_default.desc(), DeliveryOrigin.name))
    ).all()
    return [_origin_out(origin) for origin in origins]


@router.post("/origins", response_model=OriginModel, status_code=201, summary="Create a delivery origin")
async def create_origin(
    payload: OriginInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> OriginModel:
    origin = DeliveryOrigin(
        name=payload.name,
        latitude=payload.lat,
        longitude=payload.lng,
        is_default=payload.isDefault,
        is_active=payload.active,
    )
    if payload.isDefault:
        await _clear_default(session)
    session.add(origin)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="origin",
        entity_id=origin.id,
        entity_label=origin.name,
        summary=f"Created delivery origin “{origin.name}”",
        actor=actor.user,
    )
    await session.commit()
    return _origin_out(origin)


@router.patch("/origins/{origin_id}", response_model=OriginModel, summary="Update a delivery origin")
async def update_origin(
    origin_id: str,
    payload: OriginUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> OriginModel:
    origin = await session.get(DeliveryOrigin, origin_id)
    if origin is None:
        raise not_found("Delivery origin", origin_id)
    if payload.isDefault:
        await _clear_default(session)
    if payload.name is not None:
        origin.name = payload.name
    if payload.lat is not None:
        origin.latitude = payload.lat
    if payload.lng is not None:
        origin.longitude = payload.lng
    if payload.isDefault is not None:
        origin.is_default = payload.isDefault
    if payload.active is not None:
        origin.is_active = payload.active
    await audit(
        session,
        request,
        action="updated",
        entity_type="origin",
        entity_id=origin.id,
        entity_label=origin.name,
        summary=f"Updated delivery origin “{origin.name}”",
        actor=actor.user,
    )
    await session.commit()
    return _origin_out(origin)


async def _clear_default(session: SessionDep) -> None:
    for other in (await session.scalars(select(DeliveryOrigin).where(DeliveryOrigin.is_default.is_(True)))).all():
        other.is_default = False
    await session.flush()


def _origin_out(origin: DeliveryOrigin) -> OriginModel:
    return OriginModel(
        id=origin.id,
        name=origin.name,
        position=LatLngOut(lat=origin.latitude, lng=origin.longitude),
        isDefault=origin.is_default,
        active=origin.is_active,
    )
