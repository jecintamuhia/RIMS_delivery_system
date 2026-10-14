"""Pure pricing domain types.

Deliberately free of SQLAlchemy, FastAPI and httpx. The engine is handed these plain
dataclasses, which is what lets the pricing rules be unit-tested with no database, no HTTP and
no map provider in sight. The repository layer (``app.services.pricing.repository``) is
responsible for turning ORM rows into these values.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

CURRENCY_PRECISION = Decimal("0.01")

#: Computations are carried to the cent, but the amount a customer is asked to actually pay is
#: rounded to the nearest whole Kenyan shilling. This affects the final distance-based payable
#: only; official fixed destination prices are charged exactly as configured.
PAYABLE_PRECISION = Decimal("1")


class PricingModel(str, enum.Enum):
    """Which of the two pricing models produced an amount. Never blended, never implied."""

    #: Model A - an official RIMs price configured for a destination.
    FIXED_DESTINATION = "fixed_destination"
    #: Model B - road distance x the active dynamic rate configuration.
    DISTANCE_BASED = "distance_based"


class AdjustmentKind(str, enum.Enum):
    ROAD = "road"
    VEHICLE = "vehicle"
    OTHER = "other"
    MINIMUM = "minimum"
    #: The fuel adjustment applied to the distance-based rate (model B only).
    FUEL = "fuel"
    #: The line that rounds a distance-based amount to the nearest whole shilling (model B only).
    ROUNDING = "rounding"


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "KES"

    def quantised(self) -> Money:
        return Money(amount=self.amount.quantize(CURRENCY_PRECISION), currency=self.currency)

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(f"cannot add {self.currency} to {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)


@dataclass(frozen=True, slots=True)
class Adjustment:
    """One line of the calculation breakdown shown to staff and (in summary) to customers."""

    label: str
    amount: Decimal
    kind: AdjustmentKind
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PricingContext:
    """Everything the engine is allowed to consider. All resolved by services upstream."""

    #: The configured destination, or ``None`` when the location lies outside every
    #: configured RIMs destination. Model A needs a destination; model B does not.
    destination_id: str | None
    destination_name: str
    quote_date: date
    currency: str = "KES"
    distance_km: Decimal | None = None
    road_type_id: str | None = None
    road_type_name: str | None = None
    vehicle_id: str | None = None
    vehicle_name: str | None = None
    load_weight_kg: Decimal | None = None
    load_volume_m3: Decimal | None = None

    @property
    def has_road_type(self) -> bool:
        return self.road_type_id is not None

    @property
    def has_vehicle(self) -> bool:
        return self.vehicle_id is not None


@dataclass(frozen=True, slots=True)
class RuleCandidate:
    """A pricing rule reduced to the fields the engine needs."""

    id: str
    label: str | None
    base_price: Decimal
    version_id: str
    version_label: str
    #: The destination this rule prices. A rule never applies to any other destination, so this
    #: is compared in ``matches`` - omitting it would silently price every delivery from whichever
    #: single rule happened to be in the active version.
    destination_id: str
    priority: int = 0
    road_type_id: str | None = None
    vehicle_id: str | None = None
    adjustment_type: str = "none"
    adjustment_value: Decimal | None = None
    road_adjustment_type: str = "none"
    road_adjustment_value: Decimal | None = None
    vehicle_adjustment_type: str = "none"
    vehicle_adjustment_value: Decimal | None = None
    min_charge: Decimal | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool = True

    @property
    def scope_width(self) -> int:
        """How narrowly the rule is scoped. Higher = more specific."""
        return (1 if self.road_type_id else 0) + (1 if self.vehicle_id else 0)

    def is_effective_on(self, when: date) -> bool:
        if self.effective_from is not None and self.effective_from > when:
            return False
        return not (self.effective_to is not None and self.effective_to < when)

    def matches(self, context: PricingContext) -> bool:
        """Applicability test. A rule that names a qualifier only applies when it is satisfied."""
        if not self.is_active:
            return False
        if self.destination_id != context.destination_id:
            return False
        if self.road_type_id is not None and self.road_type_id != context.road_type_id:
            return False
        return not (self.vehicle_id is not None and self.vehicle_id != context.vehicle_id)


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    """The active business configuration for one calculation."""

    version_id: str | None
    version_label: str | None
    currency: str
    rules: tuple[RuleCandidate, ...] = field(default_factory=tuple)
    #: When true, a quote with no resolved road type must stop and ask rather than price it.
    requires_road_type: bool = False
    #: When true, a quote with no resolved vehicle must stop and ask rather than price it.
    requires_vehicle: bool = False
    #: Human-readable reason the active configuration cannot price at all.
    unconfigured_reason: str | None = None

    @property
    def is_pricing_configured(self) -> bool:
        return bool(self.rules) and self.unconfigured_reason is None


@dataclass(frozen=True, slots=True)
class DynamicPricingConfig:
    """The active distance-rate configuration, reduced to what the engine needs.

    Effective rate formula (the whole of model B):

        effective_rate = base_rate_per_km x (1 + fuel_adjustment_percent / 100)
        amount         = road_distance_km x effective_rate   (floored at min_charge)
    """

    version_id: str
    version_label: str
    base_rate_per_km: Decimal
    fuel_adjustment_percent: Decimal = Decimal("0")
    min_charge: Decimal | None = None
    currency: str = "KES"

    @property
    def effective_rate_per_km(self) -> Decimal:
        """The rate actually charged, rounded to the cent. Visible in every dynamic quote."""
        factor = Decimal("1") + self.fuel_adjustment_percent / Decimal("100")
        return (self.base_rate_per_km * factor).quantize(CURRENCY_PRECISION)


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    base_price: Decimal
    adjustments: tuple[Adjustment, ...]
    total: Decimal
    currency: str
    rule_id: str | None
    rule_label: str | None
    version_id: str | None
    version_label: str | None
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Which model priced this quote. Defaults to the official fixed price list.
    pricing_model: PricingModel = PricingModel.FIXED_DESTINATION
    #: For distance-based prices: every input needed to audit the amount (distance, base rate,
    #: fuel adjustment, effective rate, calculated amount, configuration label).
    pricing_details: dict[str, str] = field(default_factory=dict)

    def as_breakdown_rows(self) -> list[dict[str, str]]:
        """Serialisable form stored on the immutable quote calculation snapshot."""
        return [
            {
                "label": adjustment.label,
                "amount": str(adjustment.amount.quantize(CURRENCY_PRECISION)),
                "kind": adjustment.kind.value,
                **({"detail": adjustment.detail} if adjustment.detail else {}),
            }
            for adjustment in self.adjustments
        ]


class PriceOutcomeKind(str, enum.Enum):
    PRICED = "priced"
    UNPRICED = "unpriced"


@dataclass(frozen=True, slots=True)
class PriceOutcome:
    """The engine's verdict: either a priced breakdown or a refusal with a reason.

    There is no "provisional" or "estimated" variant on purpose. When the system cannot price
    a delivery it says so, and the caller turns that into a manual-quotation state.
    """

    kind: PriceOutcomeKind
    breakdown: PriceBreakdown | None = None
    reason: str | None = None
    reason_detail: str | None = None

    @property
    def is_priced(self) -> bool:
        return self.kind is PriceOutcomeKind.PRICED and self.breakdown is not None
