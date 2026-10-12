"""Smoke check that the pricing engine is pure and produces the expected breakdown."""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.pricing.engine import price_delivery, select_rule
from app.services.pricing.models import PricingContext, PricingPolicy, RuleCandidate

ENGINE = Path("app/services/pricing/engine.py")

FORBIDDEN_IMPORTS = {"sqlalchemy", "fastapi", "httpx", "pydantic", "app.db", "app.models", "app.api"}


def assert_engine_is_pure() -> None:
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.startswith("app."):
                imported.add(node.module.split(".")[1])
    bad = imported & FORBIDDEN_IMPORTS
    assert not bad, f"pricing engine must not import {bad}"
    print(f"engine purity OK (imports: {sorted(imported)})")


def rule(**kwargs: object) -> RuleCandidate:
    defaults: dict[str, object] = {
        "id": "r1",
        "label": None,
        "base_price": Decimal("2500.00"),
        "version_id": "v1",
        "version_label": "2026 price list",
        "destination_id": "d-nairobi",
        "effective_from": date(2026, 1, 1),
    }
    return RuleCandidate(**{**defaults, **kwargs})  # type: ignore[arg-type]


def policy(*rules: RuleCandidate) -> PricingPolicy:
    return PricingPolicy(version_id="v1", version_label="2026 price list", currency="KES", rules=rules)


def ctx(**kwargs: object) -> PricingContext:
    defaults: dict[str, object] = {
        "destination_id": "d-nairobi",
        "destination_name": "Nairobi",
        "quote_date": date(2026, 6, 1),
        "distance_km": Decimal("18.40"),
    }
    return PricingContext(**{**defaults, **kwargs})  # type: ignore[arg-type]


def test_rule_never_crosses_destinations() -> None:
    """A rule priced for one destination must not price another.

    This is the guard against the silent wrong-price failure: with destination ignored during
    matching, whichever rule sat in the active version was applied to every delivery.
    """
    nairobi_rule = rule(id="r-nairobi", destination_id="d-nairobi", base_price=Decimal("2500.00"))
    outcome = price_delivery(ctx(destination_id="d-nakuru", destination_name="Nakuru"), policy(nairobi_rule))
    assert not outcome.is_priced
    assert outcome.reason == "no_pricing_rule", outcome.reason

    # The rule does still price its own destination.
    priced = price_delivery(ctx(), policy(nairobi_rule))
    assert priced.is_priced
    assert priced.breakdown is not None
    assert priced.breakdown.total == Decimal("2500.00")


def test_engine_purity() -> None:
    """The engine must stay pure so it can be reasoned about and reused offline."""
    assert_engine_is_pure()


def test_flat_destination_price() -> None:
    out = price_delivery(ctx(), policy(rule()))
    assert out.is_priced, out
    b = out.breakdown
    assert b is not None
    assert b.base_price == Decimal("2500.00"), b.base_price
    assert b.total == Decimal("2500.00"), b.total


def test_percent_road_adjustment() -> None:
    out = price_delivery(
        ctx(road_type_id="rt-rough", road_type_name="Rough"),
        policy(rule(road_adjustment_type="percent", road_adjustment_value=Decimal("15"))),
    )
    b = out.breakdown
    assert b is not None and b.total == Decimal("2875.00"), b
    assert b.adjustments[0].kind.value == "road"


def test_fixed_vehicle_adjustment_and_minimum_charge() -> None:
    out = price_delivery(
        ctx(vehicle_id="v-truck", vehicle_name="Truck"),
        policy(
            rule(
                vehicle_adjustment_type="fixed",
                vehicle_adjustment_value=Decimal("1500"),
                min_charge=Decimal("5000"),
            )
        ),
    )
    b = out.breakdown
    assert b is not None and b.total == Decimal("5000.00"), b
    assert [a.kind.value for a in b.adjustments] == ["vehicle", "minimum"], b.adjustments


def test_priority_beats_scope_width() -> None:
    generic = rule(id="generic", priority=0)
    specific = rule(
        id="specific",
        road_type_id="rt-rough",
        road_adjustment_type="fixed",
        road_adjustment_value=Decimal("500"),
        priority=5,
    )
    chosen = select_rule(ctx(road_type_id="rt-rough"), policy(generic, specific))
    assert chosen is not None and chosen.id == "specific", chosen


def test_road_specific_rule_skipped_when_mismatch() -> None:
    specific = rule(id="specific", road_type_id="rt-rough", priority=5)
    out = price_delivery(ctx(road_type_id="rt-tarmac"), policy(specific))
    assert not out.is_priced and out.reason == "no_pricing_rule", out


def test_expired_rule_is_not_applied() -> None:
    old = rule(id="old", effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31))
    out = price_delivery(ctx(quote_date=date(2026, 6, 1)), policy(old))
    assert not out.is_priced and out.reason == "no_pricing_rule", out


def test_required_road_type_refuses_to_price() -> None:
    p = PricingPolicy(
        version_id="v1", version_label="l", currency="KES", rules=(rule(),), requires_road_type=True
    )
    out = price_delivery(ctx(), p)
    assert not out.is_priced and out.reason == "road_type_required", out


def test_unconfigured_pricing_refuses_to_price() -> None:
    out = price_delivery(ctx(), PricingPolicy(None, None, "KES", (), unconfigured_reason="no version"))
    assert not out.is_priced and out.reason == "pricing_not_configured", out


def test_empty_policy_never_guesses() -> None:
    out = price_delivery(ctx(), policy())
    assert not out.is_priced, out


#: Check order for the standalone runner.
CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("flat destination price", test_flat_destination_price),
    ("+15% road adjustment", test_percent_road_adjustment),
    ("+1500 vehicle, 5000 min", test_fixed_vehicle_adjustment_and_minimum_charge),
    ("priority wins over scope", test_priority_beats_scope_width),
    ("road rule skipped when mismatch", test_road_specific_rule_skipped_when_mismatch),
    ("expired rule is not applied", test_expired_rule_is_not_applied),
    ("required road type", test_required_road_type_refuses_to_price),
    ("unconfigured pricing", test_unconfigured_pricing_refuses_to_price),
    ("empty policy never guesses", test_empty_policy_never_guesses),
    ("rules never cross destinations", test_rule_never_crosses_destinations),
)


def main() -> int:
    assert_engine_is_pure()
    for index, (label, check) in enumerate(CHECKS, start=1):
        check()
        print(f"{index}. {label:30} -> OK")
    print("\nAll pricing engine smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
