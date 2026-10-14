"""The RIMs pricing engine.

Pure domain logic. It imports nothing from SQLAlchemy, FastAPI or httpx, holds no state and
performs no I/O, which is what makes the pricing rules directly unit-testable.

Design commitments:

* **Destination-based, not per-kilometre.** RIMs' current price list states "this destination
  costs X". That is modelled as a fixed base price per destination. Distance is carried
  through for display and for future distance-based rules, but no per-kilometre rate is invented.
* **Two models, explicitly separated.** :func:`price_delivery` is model A (official fixed
  destination price). :func:`price_by_distance` is model B (road distance x a configured
  dynamic rate). A caller asks for one of them; the engine never silently switches.
* **Only configured rules apply.** If no rule matches, the engine refuses. It never falls back
  to another destination's price, to zero, or to a percentage of nothing.
* **Transparent.** Every shilling is attributed to a labelled adjustment line.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.services.pricing.models import (
    CURRENCY_PRECISION,
    PAYABLE_PRECISION,
    Adjustment,
    AdjustmentKind,
    DynamicPricingConfig,
    PriceBreakdown,
    PriceOutcome,
    PriceOutcomeKind,
    PricingContext,
    PricingModel,
    PricingPolicy,
    RuleCandidate,
)

ZERO = Decimal("0")

#: Sorts below every real effective date, for rules that carry no date.
_MIN_DATE = date.min


class Reason:
    """Reason codes the engine refuses with. Mapped to API error codes by the quote service."""

    DESTINATION_UNSUPPORTED = "destination_unsupported"
    NO_PRICING_RULE = "no_pricing_rule"
    ROAD_TYPE_REQUIRED = "road_type_required"
    VEHICLE_REQUIRED = "vehicle_required"
    PRICING_NOT_CONFIGURED = "pricing_not_configured"
    DYNAMIC_PRICING_UNAVAILABLE = "dynamic_pricing_unavailable"
    DISTANCE_REQUIRED = "distance_required"
    INVALID_INPUT = "invalid_input"


def quantise(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_PRECISION, rounding=ROUND_HALF_UP)


def round_payable(value: Decimal) -> Decimal:
    """Round a computed amount to the nearest whole Kenyan shilling, halves up.

    Used for the final payable of a distance-based quote. The amount carried through the
    calculation is never pre-rounded: the multiplication uses the real road distance, and only
    the amount the customer is asked to pay is rounded.
    """
    return value.quantize(PAYABLE_PRECISION, rounding=ROUND_HALF_UP)


def _applicable_rules(context: PricingContext, policy: PricingPolicy) -> list[RuleCandidate]:
    return [
        rule
        for rule in policy.rules
        if rule.matches(context) and rule.is_effective_on(context.quote_date)
    ]


def select_rule(context: PricingContext, policy: PricingPolicy) -> RuleCandidate | None:
    """Pick the single rule that governs this delivery.

    Precedence, highest first:
      1. ``priority`` - explicit operator intent.
      2. scope width - a rule naming road type and vehicle beats one naming only road type.
      3. Most recently effective - the newer price list wins a tie.
    """
    candidates = _applicable_rules(context, policy)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda rule: (rule.priority, rule.scope_width, rule.effective_from or _MIN_DATE),
    )


def _percent_of(base: Decimal, percent: Decimal) -> Decimal:
    return quantise(base * percent / Decimal("100"))


def _apply_adjustment(
    base: Decimal,
    adjustment_type: str,
    adjustment_value: Decimal | None,
    *,
    kind: AdjustmentKind,
    label: str,
    detail: str | None,
) -> Adjustment | None:
    """Build one breakdown line. Returns ``None`` when the rule configures no adjustment."""
    if adjustment_type == "none":
        return None
    if adjustment_value is None:
        # Malformed configuration. Surfaced as an explicit zero-amount line is wrong;
        # returning None would silently drop a surcharge RIMs meant to apply.
        return Adjustment(
            label=label,
            amount=ZERO,
            kind=kind,
            detail=f"{detail} (no adjustment value configured)".strip(),
        )
    if adjustment_type == "fixed":
        amount = quantise(adjustment_value)
    elif adjustment_type == "percent":
        amount = _percent_of(base, adjustment_value)
    else:
        # Unknown adjustment type in data. Do not guess a meaning.
        return Adjustment(
            label=label,
            amount=ZERO,
            kind=kind,
            detail=f"{detail} (unsupported adjustment type '{adjustment_type}')".strip(),
        )
    if amount == ZERO:
        return None
    return Adjustment(label=label, amount=amount, kind=kind, detail=detail)


def _refuse(reason: str, detail: str) -> PriceOutcome:
    return PriceOutcome(kind=PriceOutcomeKind.UNPRICED, reason=reason, reason_detail=detail)


def price_delivery(context: PricingContext, policy: PricingPolicy) -> PriceOutcome:
    """Calculate the delivery charge, or explain why it cannot be calculated.

    Returns a :class:`PriceOutcome`. Callers must not substitute a price when
    ``outcome.is_priced`` is ``False``.
    """
    invalid = _validate(context, policy)
    if invalid is not None:
        return invalid

    if not policy.is_pricing_configured:
        return _refuse(
            Reason.PRICING_NOT_CONFIGURED,
            policy.unconfigured_reason or "No pricing version is currently active.",
        )

    if policy.requires_road_type and not context.has_road_type:
        return _refuse(
            Reason.ROAD_TYPE_REQUIRED,
            f"RIMs requires a road classification for deliveries to {context.destination_name}.",
        )

    if policy.requires_vehicle and not context.has_vehicle:
        return _refuse(
            Reason.VEHICLE_REQUIRED,
            f"RIMs requires a vehicle category for deliveries to {context.destination_name}.",
        )

    rule = select_rule(context, policy)
    if rule is None:
        return _refuse(
            Reason.NO_PRICING_RULE,
            (
                f"No active pricing rule matches {context.destination_name}"
                f"{_qualifier_suffix(context)} on {context.quote_date.isoformat()}."
            ),
        )

    base = quantise(rule.base_price)
    adjustments: list[Adjustment] = []
    notes: list[str] = []

    road_line = _apply_adjustment(
        base,
        rule.road_adjustment_type,
        rule.road_adjustment_value,
        kind=AdjustmentKind.ROAD,
        label="Road adjustment",
        detail=_road_detail(context),
    )
    if road_line:
        adjustments.append(road_line)
    elif context.has_road_type and rule.road_type_id:
        notes.append(f"Road type {context.road_type_name} priced into the base rate.")

    vehicle_line = _apply_adjustment(
        base,
        rule.vehicle_adjustment_type,
        rule.vehicle_adjustment_value,
        kind=AdjustmentKind.VEHICLE,
        label="Vehicle adjustment",
        detail=_vehicle_detail(context),
    )
    if vehicle_line:
        adjustments.append(vehicle_line)
    elif context.has_vehicle and rule.vehicle_id:
        notes.append(f"Vehicle category {context.vehicle_name} priced into the base rate.")

    other_line = _apply_adjustment(
        base,
        rule.adjustment_type,
        rule.adjustment_value,
        kind=AdjustmentKind.OTHER,
        label="Other adjustment",
        detail=rule.label,
    )
    if other_line:
        adjustments.append(other_line)

    total = base + sum((line.amount for line in adjustments), start=ZERO)

    if rule.min_charge is not None and total < rule.min_charge:
        shortfall = quantise(rule.min_charge - total)
        adjustments.append(
            Adjustment(
                label="Minimum charge applied",
                amount=shortfall,
                kind=AdjustmentKind.MINIMUM,
                detail=f"RIMs minimum for this destination is {rule.min_charge}.",
            )
        )
        total = rule.min_charge

    total = quantise(total)

    if context.distance_km is not None:
        notes.append(f"Road distance {context.distance_km} km was not used in this price.")

    return PriceOutcome(
        kind=PriceOutcomeKind.PRICED,
        breakdown=PriceBreakdown(
            base_price=base,
            adjustments=tuple(adjustments),
            total=total,
            currency=policy.currency,
            rule_id=rule.id,
            rule_label=rule.label or _rule_label(rule, context),
            version_id=policy.version_id or rule.version_id,
            version_label=policy.version_label or rule.version_label,
            notes=tuple(notes),
            pricing_model=PricingModel.FIXED_DESTINATION,
        ),
    )


def price_by_distance(
    context: PricingContext, config: DynamicPricingConfig | None
) -> PriceOutcome:
    """Model B: price from the actual road distance and RIMs' configured dynamic rate.

        effective rate = base rate x (1 + fuel adjustment / 100)
        calculated     = distance x effective rate, floored at the minimum charge
        payable        = calculated rounded to the nearest whole Kenyan shilling (halves up)

    The multiplication uses the real, unrounded road distance; only the final payable is rounded.
    Every input and both amounts (calculated and payable) are written into
    ``breakdown.pricing_details`` so an admin can reconstruct exactly why the system returned the
    amount. The engine refuses when no configuration is active or when no real road distance
    exists - it never invents either.
    """
    if config is None:
        return _refuse(
            Reason.DYNAMIC_PRICING_UNAVAILABLE,
            "Dynamic distance pricing is not configured, so this location cannot be priced "
            "automatically.",
        )
    if context.currency and config.currency and context.currency != config.currency:
        return _refuse(
            Reason.INVALID_INPUT,
            f"Dynamic pricing is in {config.currency} but the quote is in {context.currency}.",
        )
    distance = context.distance_km
    if distance is None:
        return _refuse(
            Reason.DISTANCE_REQUIRED,
            "Distance-based pricing needs a road distance, and none was calculated for this route.",
        )
    if distance <= ZERO:
        return _refuse(
            Reason.DISTANCE_REQUIRED,
            f"Distance-based pricing needs a positive road distance; the route reported {distance} km.",
        )

    base_rate = quantise(config.base_rate_per_km)
    effective_rate = config.effective_rate_per_km
    base_amount = quantise(distance * base_rate)
    # The calculation is carried to the cent from the *unrounded* road distance...
    calculated_amount = quantise(distance * effective_rate)
    # ...but the customer is asked to pay whole shillings.
    total = round_payable(calculated_amount)

    adjustments: list[Adjustment] = []
    fuel_amount = calculated_amount - base_amount
    if fuel_amount != ZERO:
        sign = "+" if config.fuel_adjustment_percent > ZERO else ""
        adjustments.append(
            Adjustment(
                label="Fuel adjustment",
                amount=fuel_amount,
                kind=AdjustmentKind.FUEL,
                detail=(
                    f"{sign}{config.fuel_adjustment_percent}% on the base rate: "
                    f"KES {base_rate}/km becomes KES {effective_rate}/km."
                ),
            )
        )

    rounding_amount = total - calculated_amount
    if rounding_amount != ZERO:
        adjustments.append(
            Adjustment(
                label="Rounding",
                amount=rounding_amount,
                kind=AdjustmentKind.ROUNDING,
                detail=(
                    f"KES {calculated_amount} rounded to the nearest whole shilling: "
                    f"KES {total}."
                ),
            )
        )
    rounded_amount = total

    minimum_applied = False
    if config.min_charge is not None and total < config.min_charge:
        floored = round_payable(config.min_charge)
        shortfall = floored - total
        adjustments.append(
            Adjustment(
                label="Minimum charge applied",
                amount=shortfall,
                kind=AdjustmentKind.MINIMUM,
                detail=f"RIMs minimum distance-based charge is KES {quantise(config.min_charge)}.",
            )
        )
        total = floored
        minimum_applied = True

    total = round_payable(total)

    fuel_word = ""
    if config.fuel_adjustment_percent != ZERO:
        sign = "+" if config.fuel_adjustment_percent > ZERO else ""
        fuel_word = f", {sign}{config.fuel_adjustment_percent}% fuel adjustment"
    rounded_word = f", rounded to KES {rounded_amount}" if rounding_amount != ZERO else ""
    notes = [
        (
            f"Dynamically priced: {quantise(distance)} km x KES {effective_rate}/km "
            f"(base KES {base_rate}/km{fuel_word}) = KES {calculated_amount}{rounded_word}."
        )
    ]
    if context.destination_id is None:
        notes.append("The location is outside the configured RIMs destination price list.")
    if minimum_applied and config.min_charge is not None:
        notes.append(f"Minimum dynamic charge of KES {quantise(config.min_charge)} applied.")

    return PriceOutcome(
        kind=PriceOutcomeKind.PRICED,
        breakdown=PriceBreakdown(
            base_price=base_amount,
            adjustments=tuple(adjustments),
            total=total,
            currency=config.currency,
            rule_id=None,
            rule_label=f"Distance rate · {config.version_label}",
            version_id=config.version_id,
            version_label=config.version_label,
            notes=tuple(notes),
            pricing_model=PricingModel.DISTANCE_BASED,
            pricing_details={
                "distanceKm": str(quantise(distance)),
                "baseRatePerKm": str(base_rate),
                "fuelAdjustmentPercent": str(config.fuel_adjustment_percent),
                "effectiveRatePerKm": str(effective_rate),
                "calculatedAmount": str(calculated_amount),
                "payableAmount": str(total),
                "roundingPolicy": "nearest_whole_kes",
                "configLabel": config.version_label,
                "configId": config.version_id,
                **({"minCharge": str(quantise(config.min_charge))} if config.min_charge is not None else {}),
            },
        ),
    )


def _qualifier_suffix(context: PricingContext) -> str:
    parts = []
    if context.road_type_name:
        parts.append(f"on {context.road_type_name} roads")
    if context.vehicle_name:
        parts.append(f"using {context.vehicle_name}")
    return f" ({' '.join(parts)})" if parts else ""


def _road_detail(context: PricingContext) -> str | None:
    return f"{context.road_type_name} road condition" if context.road_type_name else None


def _vehicle_detail(context: PricingContext) -> str | None:
    return context.vehicle_name


def _rule_label(rule: RuleCandidate, context: PricingContext) -> str:
    qualifiers = []
    if rule.road_type_id:
        qualifiers.append(f"road: {context.road_type_name or rule.road_type_id}")
    if rule.vehicle_id:
        qualifiers.append(f"vehicle: {context.vehicle_name or rule.vehicle_id}")
    if not qualifiers:
        return f"{context.destination_name} · base rate"
    return f"{context.destination_name} · {' · '.join(qualifiers)}"


def _validate(context: PricingContext, policy: PricingPolicy) -> PriceOutcome | None:
    if not context.destination_id:
        return _refuse(Reason.INVALID_INPUT, "A destination must be resolved before pricing.")
    if policy.currency and context.currency and policy.currency != context.currency:
        return _refuse(
            Reason.INVALID_INPUT,
            f"Pricing policy is in {policy.currency} but the quote is in {context.currency}.",
        )
    return None
