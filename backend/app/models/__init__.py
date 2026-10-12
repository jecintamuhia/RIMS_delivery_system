"""Model registry.

Importing this package registers every mapper with :class:`~app.db.base.Base`, which is what
Alembic autogenerate and ``create_all`` rely on. Services import from here rather than from
individual modules so there is one canonical import path.
"""

from __future__ import annotations

from app.models.audit import AuditLog, SystemSetting
from app.models.geography import (
    DeliveryOrigin,
    DeliveryZone,
    Destination,
    DestinationAlias,
    RoadCondition,
    RoadSegment,
    RoadType,
    VehicleCategory,
)
from app.models.pricing import (
    AdjustmentType,
    DynamicPricingVersion,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    build_scope_key,
)
from app.models.quote import (
    STEP_ORDER,
    Quote,
    QuoteCalculation,
    QuoteStatus,
    StepKey,
    StepState,
)
from app.models.user import Role, User

__all__ = [
    "STEP_ORDER",
    "AdjustmentType",
    "AuditLog",
    "DeliveryOrigin",
    "DeliveryZone",
    "Destination",
    "DestinationAlias",
    "DynamicPricingVersion",
    "PricingRule",
    "PricingVersion",
    "PricingVersionStatus",
    "Quote",
    "QuoteCalculation",
    "QuoteStatus",
    "RoadCondition",
    "RoadSegment",
    "RoadType",
    "Role",
    "StepKey",
    "StepState",
    "SystemSetting",
    "User",
    "VehicleCategory",
    "build_scope_key",
]
