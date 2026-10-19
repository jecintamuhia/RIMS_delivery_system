"""Geography and reference data.

This is the *geographical* layer only: where the goods start, where they may end, and how RIMs
classifies the roads between. It contains no prices. The pricing engine joins this data to
:class:`~app.models.pricing.PricingRule` records.

Geospatial storage note: coordinates are plain ``Float`` columns with B-tree indexes and
boundaries are GeoJSON polygons in a JSON column. That is portable across SQLite and
PostgreSQL and is sufficient for the volumes RIMs will have (hundreds of destinations). The
migration notes in ``docs/geospatial.md`` describe enabling PostGIS if per-destination polygon
indexing is ever needed; the repository/service API does not change when it is.
"""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pk_column, string_enum


class DeliveryOrigin(Base, TimestampMixin):
    """A dispatch point RIMs delivers from. Quotes route from an origin to the customer."""

    __tablename__ = "delivery_origins"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_delivery_origins_active", "is_active", "is_default"),)


class DeliveryZone(Base, TimestampMixin):
    """A RIMs-defined zone grouping destinations (e.g. an internal or regional grouping)."""

    __tablename__ = "delivery_zones"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    destinations: Mapped[list[Destination]] = relationship(back_populates="zone")


class Destination(Base, TimestampMixin):
    """A place RIMs delivers to, and the anchor for destination-based pricing."""

    __tablename__ = "destinations"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    zone_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("delivery_zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    county: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    catchment_radius_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    zone: Mapped[DeliveryZone | None] = relationship(back_populates="destinations")
    aliases: Mapped[list[DestinationAlias]] = relationship(
        back_populates="destination", cascade="all, delete-orphan", order_by="DestinationAlias.alias"
    )

    __table_args__ = (
        Index("ix_destinations_active_name", "is_active", "name"),
        # Supports the configured-radius lookup without loading every destination into memory.
        Index("ix_destinations_geo", "latitude", "longitude"),
    )


class DestinationAlias(Base):
    """Alternative spellings a geocoder may return for a destination town/area.

    Aliases exist so destination resolution is a data lookup, not a hardcoded string
    comparison in application code.
    """

    __tablename__ = "destination_aliases"

    id: Mapped[str] = pk_column()
    destination_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    destination: Mapped[Destination] = relationship(back_populates="aliases")

    __table_args__ = (
        Index("uq_destination_alias", "destination_id", "alias", unique=True),
        Index("ix_destination_alias_lookup", "alias", "is_active"),
    )


class RoadCondition(str, enum.Enum):
    """How RIMs classifies a road for pricing. Extending this list is a code change *and* a
    data migration; new classifications must be agreed with RIMs before they are priced."""

    TARMAC = "tarmac"
    ROUGH = "rough"
    MIXED = "mixed"
    UNCLASSIFIED = "unclassified"


class RoadType(Base, TimestampMixin):
    """RIMs-managed road classification used by road-type pricing adjustments."""

    __tablename__ = "road_types"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition: Mapped[RoadCondition] = mapped_column(
        string_enum(RoadCondition, length=16),
        nullable=False,
        default=RoadCondition.UNCLASSIFIED,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RoadSegment(Base, TimestampMixin):
    """A stretch of road RIMs has classified, used to derive a quote's road type.

    Segments are matched by radius around their representative point. A segment may be scoped
    to a destination so the same surface classification can differ between areas.
    """

    __tablename__ = "road_segments"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    road_type_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("road_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    destination_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("destinations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("5.00"))
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    road_type: Mapped[RoadType] = relationship()

    __table_args__ = (Index("ix_road_segments_geo", "latitude", "longitude", "is_active"),)


class VehicleCategory(Base, TimestampMixin):
    """A vehicle class RIMs prices by. Categories are configuration, never hardcoded."""

    __tablename__ = "vehicle_categories"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    #: Load ceiling used to pick a category when the customer supplies load information.
    min_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
