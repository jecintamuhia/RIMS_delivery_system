"""Pricing domain package.

``engine`` is pure and dependency-free; ``repository`` is the only module that touches the
database. Import the engine directly in tests: it must stay independent of transport.
"""

from app.services.pricing.engine import Reason, price_delivery, select_rule
from app.services.pricing.models import (
    Adjustment,
    AdjustmentKind,
    Money,
    PriceBreakdown,
    PriceOutcome,
    PriceOutcomeKind,
    PricingContext,
    PricingPolicy,
    RuleCandidate,
)

__all__ = [
    "Adjustment",
    "AdjustmentKind",
    "Money",
    "PriceBreakdown",
    "PriceOutcome",
    "PriceOutcomeKind",
    "PricingContext",
    "PricingPolicy",
    "Reason",
    "RuleCandidate",
    "price_delivery",
    "select_rule",
]
