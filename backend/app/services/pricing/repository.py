"""Bridges ORM rows to the pure pricing domain types.

This is the *only* place that knows both SQLAlchemy and :mod:`app.services.pricing.engine`.
The engine itself stays I/O-free.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AdjustmentType,
    DynamicPricingVersion,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    RoadType,
    VehicleCategory,
)
from app.services.pricing.models import DynamicPricingConfig, PricingPolicy, RuleCandidate


def to_candidate(rule: PricingRule, version: PricingVersion) -> RuleCandidate:
    return RuleCandidate(
        id=rule.id,
        label=rule.label,
        base_price=Decimal(rule.base_price),
        version_id=version.id,
        version_label=version.label,
        destination_id=rule.destination_id,
        priority=rule.priority,
        road_type_id=rule.road_type_id,
        vehicle_id=rule.vehicle_id,
        adjustment_type=rule.adjustment_type.value
        if isinstance(rule.adjustment_type, AdjustmentType)
        else str(rule.adjustment_type),
        adjustment_value=Decimal(rule.adjustment_value) if rule.adjustment_value is not None else None,
        road_adjustment_type=rule.road_adjustment_type.value
        if isinstance(rule.road_adjustment_type, AdjustmentType)
        else str(rule.road_adjustment_type),
        road_adjustment_value=Decimal(rule.road_adjustment_value)
        if rule.road_adjustment_value is not None
        else None,
        vehicle_adjustment_type=rule.vehicle_adjustment_type.value
        if isinstance(rule.vehicle_adjustment_type, AdjustmentType)
        else str(rule.vehicle_adjustment_type),
        vehicle_adjustment_value=Decimal(rule.vehicle_adjustment_value)
        if rule.vehicle_adjustment_value is not None
        else None,
        min_charge=Decimal(rule.min_charge) if rule.min_charge is not None else None,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        is_active=rule.is_active,
    )


async def load_active_policy(
    session: AsyncSession,
    *,
    when: date,
    requires_road_type: bool = False,
    requires_vehicle: bool = False,
) -> PricingPolicy:
    """Load the pricing policy in force on ``when``.

    Prefers the single ACTIVE version. If none is active but a version's own effective window
    covers ``when``, that version is used and the situation is reported to the caller, because
    "prices exist but nobody activated them" is an admin problem - not a customer one.
    """
    active = await session.scalar(
        select(PricingVersion)
        .where(PricingVersion.status == PricingVersionStatus.ACTIVE)
        .options(selectinload(PricingVersion.rules))
        .limit(1)
    )

    unconfigured_reason: str | None = None
    version = active
    if version is None:
        version = await session.scalar(
            select(PricingVersion)
            .where(PricingVersion.status != PricingVersionStatus.DRAFT)
            .options(selectinload(PricingVersion.rules))
            .order_by(PricingVersion.effective_from.desc())
            .limit(1)
        )
        if version is not None:
            unconfigured_reason = (
                f"Pricing version '{version.label}' has not been activated. "
                "Activate a pricing version in the admin area."
            )

    if version is None:
        return PricingPolicy(
            version_id=None,
            version_label=None,
            currency="KES",
            rules=(),
            requires_road_type=requires_road_type,
            requires_vehicle=requires_vehicle,
            unconfigured_reason="No pricing version has been configured yet.",
        )

    candidates = tuple(to_candidate(rule, version) for rule in version.rules)
    return PricingPolicy(
        version_id=version.id,
        version_label=version.label,
        currency=version.currency,
        rules=candidates,
        requires_road_type=requires_road_type,
        requires_vehicle=requires_vehicle,
        unconfigured_reason=unconfigured_reason,
    )


def to_dynamic_config(row: DynamicPricingVersion) -> DynamicPricingConfig:
    return DynamicPricingConfig(
        version_id=row.id,
        version_label=row.label,
        base_rate_per_km=Decimal(row.base_rate_per_km),
        fuel_adjustment_percent=Decimal(row.fuel_adjustment_percent),
        min_charge=Decimal(row.min_charge) if row.min_charge is not None else None,
        currency=row.currency,
    )


async def load_active_dynamic_pricing(session: AsyncSession) -> DynamicPricingConfig | None:
    """The active distance-rate configuration, or ``None`` when model B is switched off.

    Returning ``None`` is what makes "dynamic pricing is not configured" an honest refusal
    rather than a defaulted rate: no configuration, no price.
    """
    row = await session.scalar(
        select(DynamicPricingVersion)
        .where(DynamicPricingVersion.status == PricingVersionStatus.ACTIVE)
        .limit(1)
    )
    return to_dynamic_config(row) if row is not None else None


async def find_rule_by_id(session: AsyncSession, rule_id: str) -> PricingRule | None:
    return await session.scalar(
        select(PricingRule)
        .where(PricingRule.id == rule_id)
        .options(
            selectinload(PricingRule.version),
            selectinload(PricingRule.destination),
            selectinload(PricingRule.road_type),
            selectinload(PricingRule.vehicle),
        )
    )


async def rule_uses_road_types(session: AsyncSession, version_id: str | None = None) -> bool:
    stmt = select(PricingRule.id).where(PricingRule.road_type_id.is_not(None)).limit(1)
    if version_id:
        stmt = stmt.where(PricingRule.version_id == version_id)
    return (await session.scalar(stmt)) is not None


async def rule_uses_vehicles(session: AsyncSession, version_id: str | None = None) -> bool:
    stmt = select(PricingRule.id).where(PricingRule.vehicle_id.is_not(None)).limit(1)
    if version_id:
        stmt = stmt.where(PricingRule.version_id == version_id)
    return (await session.scalar(stmt)) is not None


async def current_base_price_for(
    session: AsyncSession, destination_id: str, when: date, version_id: str | None
) -> Decimal | None:
    """Cheapest active base price for a destination, used for the destinations list summary."""
    stmt = select(PricingRule.base_price).where(
        PricingRule.destination_id == destination_id,
        PricingRule.is_active.is_(True),
        PricingRule.effective_from <= when,
    )
    if version_id:
        stmt = stmt.where(PricingRule.version_id == version_id)
    stmt = stmt.order_by(PricingRule.base_price.asc()).limit(1)
    value = await session.scalar(stmt)
    return Decimal(value) if value is not None else None


async def list_road_types(session: AsyncSession, *, active_only: bool = False) -> list[RoadType]:
    stmt = select(RoadType).order_by(RoadType.name)
    if active_only:
        stmt = stmt.where(RoadType.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def list_vehicles(session: AsyncSession, *, active_only: bool = False) -> list[VehicleCategory]:
    stmt = select(VehicleCategory).order_by(VehicleCategory.sort_order, VehicleCategory.name)
    if active_only:
        stmt = stmt.where(VehicleCategory.is_active.is_(True))
    return list((await session.scalars(stmt)).all())
