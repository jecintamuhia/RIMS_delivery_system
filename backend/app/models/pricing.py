"""Pricing versions, rules and the dynamic distance-rate configuration.

RIMs' price list is destination-based, so the canonical rule is "this destination costs X".
The schema deliberately also supports vehicle-specific, road-type-specific and
percentage/fixed adjustments so more sophisticated pricing can be configured later - but a
rule only affects a quote if it exists here. Nothing is inferred.

Destinations with no configured price are priced by the second, explicitly separate model:
:class:`DynamicPricingVersion` (road distance x configured rate). The two models never blend:
a fixed destination price is never recomputed from distance or fuel.

Immutability: editing an *active* rule is not allowed through the API. Prices change by
creating a new :class:`PricingVersion` with new rules, which keeps every historical quote
explainable.

Uniqueness: a version may contain only one rule per destination/road-type/vehicle combination.
SQL treats NULLs as distinct in unique indexes, so the combination is enforced through a
non-null ``scope_key`` (``dest|road|vehicle`` with ``*`` for "any") instead.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pk_column, string_enum

if TYPE_CHECKING:  # pragma: no cover
    from app.models.geography import Destination, RoadType, VehicleCategory
else:  # SQLAlchemy resolves these by class at mapper configuration time.
    from app.models.geography import Destination, RoadType, VehicleCategory

Money = Numeric(12, 2)


class PricingVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class PricingVersion(Base, TimestampMixin):
    """A dated, named batch of pricing rules. At most one version is active at a time."""

    __tablename__ = "pricing_versions"

    id: Mapped[str] = pk_column()
    label: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[PricingVersionStatus] = mapped_column(
        string_enum(PricingVersionStatus, length=16),
        nullable=False,
        default=PricingVersionStatus.DRAFT,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Where the data came from, e.g. ``csv-import`` - the audit trail back to RIMs' own list.
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    validation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    rules: Mapped[list[PricingRule]] = relationship(
        back_populates="version", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="version_date_order"),
        Index("ix_pricing_versions_status_dates", "status", "effective_from", "effective_to"),
    )

    def is_effective_on(self, when: date) -> bool:
        if self.effective_from > when:
            return False
        return self.effective_to is None or self.effective_to >= when


class DynamicPricingVersion(Base, TimestampMixin):
    """Versioned configuration of the distance-based ("dynamic") pricing model.

    Model B of the pricing architecture:

        road distance x effective rate -> price

    where ``effective rate = base_rate_per_km x (1 + fuel_adjustment_percent / 100)``.

    It is deliberately a *separate* object from :class:`PricingVersion`. Model A (official
    fixed destination prices) is never modified by a change here: fuel adjustments and base
    rates apply only to destinations that have no configured RIMs price, unless RIMs changes
    the model itself. Only one version is ``active`` at a time; activating a new one retires
    the previous, and historical quotes keep the id of the configuration they were priced with.
    """

    __tablename__ = "dynamic_pricing_versions"

    id: Mapped[str] = pk_column()
    label: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[PricingVersionStatus] = mapped_column(
        string_enum(PricingVersionStatus, length=16),
        nullable=False,
        default=PricingVersionStatus.DRAFT,
    )
    base_rate_per_km: Mapped[Decimal] = mapped_column(Money, nullable=False)
    fuel_adjustment_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("0")
    )
    min_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("base_rate_per_km > 0", name="dynamic_base_rate_positive"),
        CheckConstraint("min_charge IS NULL OR min_charge >= 0", name="dynamic_min_charge_non_negative"),
        CheckConstraint(
            "fuel_adjustment_percent >= -100 AND fuel_adjustment_percent <= 1000",
            name="dynamic_fuel_adjustment_range",
        ),
        Index("ix_dynamic_pricing_versions_status", "status", "activated_at"),
    )


class AdjustmentType(str, enum.Enum):
    NONE = "none"
    FIXED = "fixed"
    PERCENT = "percent"


def build_scope_key(destination_id: str, road_type_id: str | None, vehicle_id: str | None) -> str:
    """Canonical uniqueness key for a rule's scope. Empty qualifiers collapse to ``*``."""
    return f"{destination_id}|{road_type_id or '*'}|{vehicle_id or '*'}"


class PricingRule(Base):
    """One destination price, optionally qualified by vehicle and road type.

    ``base_price`` is the destination price RIMs quotes. ``adjustment_type``/``adjustment_value``
    express a road-type or vehicle surcharge on top of it. ``min_charge`` is only applied when
    RIMs configures it.
    """

    __tablename__ = "pricing_rules"

    id: Mapped[str] = pk_column()
    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pricing_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    destination_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    road_type_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("road_types.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("vehicle_categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(140), nullable=False)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    base_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    adjustment_type: Mapped[AdjustmentType] = mapped_column(
        string_enum(AdjustmentType, length=16),
        nullable=False,
        default=AdjustmentType.NONE,
    )
    adjustment_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    road_adjustment_type: Mapped[AdjustmentType] = mapped_column(
        string_enum(AdjustmentType, length=16),
        nullable=False,
        default=AdjustmentType.NONE,
    )
    road_adjustment_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    vehicle_adjustment_type: Mapped[AdjustmentType] = mapped_column(
        string_enum(AdjustmentType, length=16),
        nullable=False,
        default=AdjustmentType.NONE,
    )
    vehicle_adjustment_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    version: Mapped[PricingVersion] = relationship(back_populates="rules")
    destination: Mapped[Destination] = relationship()
    road_type: Mapped[RoadType | None] = relationship()
    vehicle: Mapped[VehicleCategory | None] = relationship()

    __table_args__ = (
        CheckConstraint("base_price >= 0", name="base_price_non_negative"),
        CheckConstraint("min_charge IS NULL OR min_charge >= 0", name="min_charge_non_negative"),
        CheckConstraint(
            "(adjustment_type = 'none' AND adjustment_value IS NULL)"
            " OR (adjustment_type IN ('fixed', 'percent') AND adjustment_value IS NOT NULL)",
            name="adjustment_value_matches_type",
        ),
        CheckConstraint(
            "(road_adjustment_type = 'none' AND road_adjustment_value IS NULL)"
            " OR (road_adjustment_type IN ('fixed', 'percent') AND road_adjustment_value IS NOT NULL)",
            name="road_adjustment_value_matches_type",
        ),
        CheckConstraint(
            "(vehicle_adjustment_type = 'none' AND vehicle_adjustment_value IS NULL)"
            " OR (vehicle_adjustment_type IN ('fixed', 'percent') AND vehicle_adjustment_value IS NOT NULL)",
            name="vehicle_adjustment_value_matches_type",
        ),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="rule_date_order"),
        Index("uq_pricing_rule_scope", "version_id", "scope_key", unique=True),
        Index("ix_pricing_rules_resolution", "destination_id", "is_active", "priority", "effective_from"),
    )

    @property
    def scope(self) -> tuple[bool, bool]:
        """(has road-type qualifier, has vehicle qualifier). Used to break priority ties."""
        return (self.road_type_id is not None, self.vehicle_id is not None)

    @property
    def scope_width(self) -> int:
        return sum(self.scope)

    def is_effective_on(self, when: date) -> bool:
        if self.effective_from > when:
            return False
        return self.effective_to is None or self.effective_to >= when

    @property
    def display_label(self) -> str:
        return self.label or self.scope_description

    @property
    def scope_description(self) -> str:
        parts = []
        if self.road_type is not None:
            parts.append(f"road: {self.road_type.name}")
        if self.vehicle is not None:
            parts.append(f"vehicle: {self.vehicle.name}")
        return " · ".join(parts) if parts else "base rate"
