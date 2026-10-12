"""Delivery quotes and their immutable calculation snapshots.

A :class:`Quote` is the customer-visible record and its mutable status/progress state.
A :class:`QuoteCalculation` is the frozen explanation of one pricing run: base price, every
adjustment, the rule that won, and the pricing version. Calculation rows are never updated,
so a quote from six months ago can still be explained after the price list has changed.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, ensure_utc, pk_column, string_enum


class QuoteStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class StepKey(str, enum.Enum):
    """The pipeline stages a customer watches. Reported verbatim to the UI."""

    LOCATION = "location"
    ROUTE = "route"
    DESTINATION = "destination"
    PRICING = "pricing"
    ESTIMATE = "estimate"


STEP_ORDER: tuple[StepKey, ...] = (
    StepKey.LOCATION,
    StepKey.ROUTE,
    StepKey.DESTINATION,
    StepKey.PRICING,
    StepKey.ESTIMATE,
)


class StepState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Quote(Base, TimestampMixin):
    """One delivery quote request and its current state."""

    __tablename__ = "quotes"

    id: Mapped[str] = pk_column()
    status: Mapped[QuoteStatus] = mapped_column(
        string_enum(QuoteStatus, length=16),
        nullable=False,
        default=QuoteStatus.PROCESSING,
        index=True,
    )
    #: Progress of each pipeline stage, serialised as ``[{"key": "...", "state": "..."}]``.
    steps: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)

    # ── input ──
    origin_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("delivery_origins.id", ondelete="SET NULL"), nullable=True
    )
    input_label: Mapped[str] = mapped_column(String(320), nullable=False)
    input_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    input_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    #: Provider-supplied location id, when the customer picked a search result.
    location_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Free-text reference the customer supplied with their order (their order/invoice number).
    customer_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    #: Optional load hints used for vehicle selection.
    load_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    load_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)

    # ── resolved geography (geographical layer only, never prices) ──
    resolved_label: Mapped[str | None] = mapped_column(String(320), nullable=True)
    resolved_secondary: Mapped[str | None] = mapped_column(String(320), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)

    route_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    route_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_geometry: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    route_summary: Mapped[str | None] = mapped_column(String(320), nullable=True)
    routing_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geocoding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    destination_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    destination_match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    road_type_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("road_types.id", ondelete="SET NULL"), nullable=True
    )
    road_segment_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("road_segments.id", ondelete="SET NULL"), nullable=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("vehicle_categories.id", ondelete="SET NULL"), nullable=True
    )

    # ── outcome ──
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    #: Which pricing model produced the fee: ``fixed_destination`` (official RIMs price list)
    #: or ``distance_based`` (dynamic rate x road distance). Never implied - always recorded.
    pricing_model: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pricing_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("pricing_versions.id", ondelete="SET NULL"), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(400), nullable=True)
    failure_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    origin: Mapped[DeliveryOrigin | None] = relationship()
    destination: Mapped[Destination | None] = relationship()
    road_type: Mapped[RoadType | None] = relationship()
    vehicle: Mapped[VehicleCategory | None] = relationship()
    pricing_version: Mapped[PricingVersion | None] = relationship()
    #: Eager by default: every consumer of a quote (customer or admin) needs the latest
    #: calculation to state which pricing model produced the amount.
    calculations: Mapped[list[QuoteCalculation]] = relationship(
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteCalculation.created_at.desc()",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_quotes_status_created", "status", "created_at"),
        Index("ix_quotes_destination_created", "destination_id", "created_at"),
        Index("ix_quotes_listing", "is_archived", "created_at"),
    )

    @property
    def is_resolved(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def is_priced(self) -> bool:
        return self.fee_amount is not None and self.fee_amount > 0

    def is_expired(self, now: datetime) -> bool:
        """A priced quote is only valid for the configured window."""
        expires_at = ensure_utc(self.expires_at)
        if expires_at is None:
            return False
        return expires_at <= (now if now.tzinfo else now.replace(tzinfo=UTC))


class QuoteCalculation(Base):
    """Immutable snapshot of one pricing run. Never mutated once written."""

    __tablename__ = "quote_calculations"

    id: Mapped[str] = pk_column()
    quote_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: ``fixed_destination`` or ``distance_based`` - which model priced this run.
    pricing_model: Mapped[str] = mapped_column(
        String(24), nullable=False, default="fixed_destination", server_default="'fixed_destination'"
    )
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    #: ``[{"label": "...", "amount": "-250.00", "kind": "road"}]`` - ordered as applied.
    breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rule_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pricing_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pricing_version_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: For distance-based quotes: the dynamic pricing configuration used. Separate from
    #: ``pricing_version_id`` (which addresses the fixed price list) so the two models can
    #: never be confused when explaining a historical amount.
    dynamic_pricing_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("dynamic_pricing_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: Full transparency record for a distance-based price: distance, base rate, fuel
    #: adjustment, effective rate, calculated amount and the configuration label.
    pricing_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: Factors that were resolved but did not change the price (e.g. no rule for road type).
    notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    quote: Mapped[Quote] = relationship(back_populates="calculations")


if TYPE_CHECKING:  # pragma: no cover
    from app.models.geography import DeliveryOrigin, Destination, RoadType, VehicleCategory
    from app.models.pricing import PricingVersion
else:
    from app.models.geography import DeliveryOrigin, Destination, RoadType, VehicleCategory
    from app.models.pricing import PricingVersion
