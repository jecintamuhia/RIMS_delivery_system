"""System settings.

Operational configuration an administrator can change without a redeploy: the dispatch point,
contact details, the default road type and vehicle, and which pricing version is active.
Secrets are not here - those come from the environment.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeliveryOrigin, SystemSetting

COMPANY_NAME = "company_name"
COMPANY_LOGO_URL = "company_logo_url"
CONTACT_PHONE = "contact_phone"
CONTACT_EMAIL = "contact_email"
DEFAULT_ORIGIN_ID = "default_origin_id"
DEFAULT_ROAD_TYPE_ID = "default_road_type_id"
DEFAULT_VEHICLE_ID = "default_vehicle_id"
MAP_ZOOM = "map_zoom"
MAP_TILE_URL = "map_tile_url"
MAP_ATTRIBUTION = "map_attribution"

DESCRIPTIONS = {
    COMPANY_NAME: "Company name shown to customers on the delivery calculator.",
    COMPANY_LOGO_URL: "URL of the official company logo shown in the app and the opening sequence.",
    CONTACT_PHONE: "Phone number customers are given when a quote needs a manual quotation.",
    CONTACT_EMAIL: "Email address customers are given when a quote needs a manual quotation.",
    DEFAULT_ORIGIN_ID: "Which dispatch point deliveries are routed and priced from.",
    DEFAULT_ROAD_TYPE_ID: "Road classification applied when no confirmed road segment covers a delivery point.",
    DEFAULT_VEHICLE_ID: "Vehicle category applied when the delivery has no load information.",
    MAP_ZOOM: "Default map zoom level for the customer map.",
    MAP_TILE_URL: "Optional tile template URL overriding the built-in OpenStreetMap tiles.",
    MAP_ATTRIBUTION: "Attribution text shown on the customer map.",
}


async def get_value(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    return row.value if row is not None else default


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.scalars(select(SystemSetting))).all()
    return {row.key: row.value for row in rows}


async def set_value(session: AsyncSession, key: str, value: Any, *, user_id: str | None = None) -> SystemSetting:
    row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is None:
        row = SystemSetting(key=key, value=value, description=DESCRIPTIONS.get(key), updated_by_id=user_id)
        session.add(row)
    else:
        row.value = value
        row.updated_by_id = user_id
    await session.flush()
    return row


async def resolve_dispatch_origin(session: AsyncSession) -> DeliveryOrigin | None:
    """The origin the map centres on and the public config reports."""
    configured = await get_value(session, DEFAULT_ORIGIN_ID)
    if configured:
        origin = await session.scalar(
            select(DeliveryOrigin).where(DeliveryOrigin.id == str(configured))
        )
        if origin is not None and origin.is_active:
            return origin
    return await session.scalar(
        select(DeliveryOrigin)
        .where(DeliveryOrigin.is_active.is_(True))
        .order_by(DeliveryOrigin.is_default.desc(), DeliveryOrigin.created_at)
        .limit(1)
    )
