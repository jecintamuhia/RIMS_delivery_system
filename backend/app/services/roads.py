"""Road and vehicle classification.

Road condition is a **business/geographical** layer, not something to guess from a routing API.
A delivery's road type comes from road segments RIMs has configured *and confirmed*, or from a
default road type RIMs has nominated as a setting. If neither exists the road type is simply
unresolved, and whether that blocks pricing is a business rule read from the pricing
configuration - never an invented default.

Vehicle category is likewise configuration: an explicit request, capacity matching against
configured categories, or RIMs' configured default. There is no hardcoded "small van".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RoadSegment, RoadType, SystemSetting, VehicleCategory
from app.observability import log_event
from app.services.geo import haversine_km

logger = logging.getLogger("app.services.roads")

SOURCE_SEGMENT = "road_segment"
SOURCE_DEFAULT = "default_road_type"
SOURCE_UNRESOLVED = "unresolved"

VEHICLE_REQUESTED = "requested"
VEHICLE_CAPACITY = "capacity_match"
VEHICLE_DEFAULT = "default"
VEHICLE_UNKNOWN = "unknown_vehicle"
VEHICLE_OVER_CAPACITY = "over_capacity"
VEHICLE_UNRESOLVED = "unresolved"

DEFAULT_ROAD_TYPE_KEY = "default_road_type_id"
DEFAULT_VEHICLE_KEY = "default_vehicle_id"


@dataclass(frozen=True, slots=True)
class RoadClassification:
    road_type: RoadType | None
    segment: RoadSegment | None
    source: str
    #: Why it is unresolved, so the quote can report the real reason.
    detail: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.road_type is not None


@dataclass(frozen=True, slots=True)
class VehicleResolution:
    vehicle: VehicleCategory | None
    source: str
    detail: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.vehicle is not None


async def _setting_id(session: AsyncSession, key: str) -> str | None:
    value = await session.scalar(select(SystemSetting.value).where(SystemSetting.key == key))
    return str(value) if value else None


async def load_default_road_type(session: AsyncSession) -> RoadType | None:
    configured = await _setting_id(session, DEFAULT_ROAD_TYPE_KEY)
    if not configured:
        return None
    return await session.scalar(
        select(RoadType).where(RoadType.id == configured, RoadType.is_active.is_(True))
    )


async def load_default_vehicle(session: AsyncSession) -> VehicleCategory | None:
    configured = await _setting_id(session, DEFAULT_VEHICLE_KEY)
    if not configured:
        return None
    return await session.scalar(
        select(VehicleCategory).where(VehicleCategory.id == configured, VehicleCategory.is_active.is_(True))
    )


async def classify_road(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    destination_id: str | None = None,
) -> RoadClassification:
    """Resolve the road type for a delivery point from RIMs' own configuration.

    Only ``is_confirmed`` segments are honoured: an unreviewed classification must never
    silently change what a customer is charged.
    """
    segments = await _candidate_segments(session, destination_id)

    best: tuple[float, RoadSegment] | None = None
    for segment in segments:
        distance = haversine_km(lat, lng, segment.latitude, segment.longitude)
        if distance <= float(segment.radius_km) and (best is None or distance < best[0]):
            best = (distance, segment)

    if best is not None:
        distance, segment = best
        road_type = await session.scalar(
            select(RoadType).where(RoadType.id == segment.road_type_id, RoadType.is_active.is_(True))
        )
        if road_type is not None:
            log_event(
                logger,
                logging.INFO,
                "road classified from configured segment",
                source=SOURCE_SEGMENT,
                distance_km=round(distance, 3),
            )
            return RoadClassification(road_type, segment, SOURCE_SEGMENT)

    default = await load_default_road_type(session)
    if default is not None:
        return RoadClassification(default, None, SOURCE_DEFAULT)

    return RoadClassification(
        None,
        None,
        SOURCE_UNRESOLVED,
        "No road classification has been configured for this delivery point.",
    )


async def _candidate_segments(session: AsyncSession, destination_id: str | None) -> list[RoadSegment]:
    base = select(RoadSegment).where(
        RoadSegment.is_active.is_(True),
        RoadSegment.is_confirmed.is_(True),
    )
    if destination_id:
        scoped = list((await session.scalars(base.where(RoadSegment.destination_id == destination_id))).all())
        if scoped:
            return scoped
        # No destination-specific segments: fall back to general ones.
        return list((await session.scalars(base.where(RoadSegment.destination_id.is_(None)))).all())
    return list((await session.scalars(base.where(RoadSegment.destination_id.is_(None)))).all())


async def resolve_vehicle(
    session: AsyncSession,
    *,
    weight_kg: Decimal | None = None,
    volume_m3: Decimal | None = None,
    requested_vehicle_id: str | None = None,
) -> VehicleResolution:
    """Pick the vehicle category for a delivery."""
    if requested_vehicle_id:
        requested = await session.scalar(
            select(VehicleCategory).where(
                VehicleCategory.id == requested_vehicle_id, VehicleCategory.is_active.is_(True)
            )
        )
        if requested is not None:
            return VehicleResolution(requested, VEHICLE_REQUESTED)
        return VehicleResolution(
            None,
            VEHICLE_UNKNOWN,
            f"Vehicle '{requested_vehicle_id}' is not an active vehicle category.",
        )

    if weight_kg is not None or volume_m3 is not None:
        stmt = select(VehicleCategory).where(VehicleCategory.is_active.is_(True))
        if weight_kg is not None:
            stmt = stmt.where(
                (VehicleCategory.max_weight_kg.is_(None)) | (VehicleCategory.max_weight_kg >= weight_kg)
            )
        if volume_m3 is not None:
            stmt = stmt.where(
                (VehicleCategory.max_volume_m3.is_(None)) | (VehicleCategory.max_volume_m3 >= volume_m3)
            )
        candidates = list(
            (await session.scalars(stmt.order_by(VehicleCategory.sort_order, VehicleCategory.name))).all()
        )
        if candidates:
            fitting = [c for c in candidates if _fits(c, weight_kg, volume_m3)]
            if fitting:
                # Smallest category that can carry the load: the compliant option, not a guess.
                return VehicleResolution(fitting[0], VEHICLE_CAPACITY)
            return VehicleResolution(
                None,
                VEHICLE_OVER_CAPACITY,
                "The supplied load exceeds every configured vehicle category.",
            )

    default = await load_default_vehicle(session)
    if default is not None:
        return VehicleResolution(default, VEHICLE_DEFAULT)
    return VehicleResolution(
        None,
        VEHICLE_UNRESOLVED,
        "No vehicle category has been configured for this delivery.",
    )


def _fits(category: VehicleCategory, weight_kg: Decimal | None, volume_m3: Decimal | None) -> bool:
    if weight_kg is not None and category.max_weight_kg is not None and Decimal(category.max_weight_kg) < weight_kg:
        return False
    return not (
        volume_m3 is not None
        and category.max_volume_m3 is not None
        and Decimal(category.max_volume_m3) < volume_m3
    )
