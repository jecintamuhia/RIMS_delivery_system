"""Admin write schemas for configurable resources.

Validation here is the last line of defence against nonsense pricing configuration. Cross-field
rules that the pricing engine depends on (an adjustment value must exist when the type is not
``none``, dates must be ordered) are enforced server-side, not only in the browser form.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AdjustmentTypeLiteral = Literal["none", "fixed", "percent"]
RoleLiteral = Literal["admin", "editor", "viewer"]
RoadConditionLiteral = Literal["tarmac", "rough", "mixed", "unclassified"]


class ZoneInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    active: bool = True


class ZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class AliasInput(BaseModel):
    alias: str = Field(min_length=1, max_length=160)


class DestinationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    zoneId: str | None = None
    county: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    boundary: dict[str, object] | None = None
    catchmentRadiusKm: Decimal | None = Field(default=None, ge=0, le=500)
    active: bool = True
    aliases: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _pair_coordinates(self) -> DestinationInput:
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must both be provided, or both omitted")
        if self.boundary is not None and self.boundary.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("boundary must be a GeoJSON Polygon or MultiPolygon")
        if self.boundary is not None and "coordinates" not in self.boundary:
            raise ValueError("boundary is missing 'coordinates'")
        return self


class DestinationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    zoneId: str | None = None
    county: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    boundary: dict[str, object] | None = None
    catchmentRadiusKm: Decimal | None = Field(default=None, ge=0, le=500)
    active: bool | None = None
    aliases: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _pair_coordinates(self) -> DestinationUpdate:
        if (self.lat is None) != (self.lng is None) and self.lat is not None and self.lng is not None:
            raise ValueError("lat and lng must both be provided, or both omitted")
        if self.boundary is not None and self.boundary.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("boundary must be a GeoJSON Polygon or MultiPolygon")
        return self


class RoadTypeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    condition: RoadConditionLiteral = "unclassified"
    active: bool = True


class RoadTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    condition: RoadConditionLiteral | None = None
    active: bool | None = None


class RoadSegmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    roadTypeId: str
    destinationId: str | None = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radiusKm: Decimal = Field(default=Decimal("5.00"), gt=0, le=500)
    confirmed: bool = False
    active: bool = True


class RoadSegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    roadTypeId: str | None = None
    destinationId: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radiusKm: Decimal | None = Field(default=None, gt=0, le=500)
    confirmed: bool | None = None
    active: bool | None = None


class VehicleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    maxWeightKg: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    maxVolumeM3: Decimal | None = Field(default=None, gt=0, le=10_000)
    sortOrder: int = 0
    active: bool = True


class VehicleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)
    maxWeightKg: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    maxVolumeM3: Decimal | None = Field(default=None, gt=0, le=10_000)
    sortOrder: int | None = None
    active: bool | None = None


class OriginInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    isDefault: bool = False
    active: bool = True


class OriginUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    isDefault: bool | None = None
    active: bool | None = None


class ValidationRequest(BaseModel):
    """Reviewer confirmation recorded when a version is approved for activation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=500)


class PricingVersionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)
    effectiveFrom: date
    effectiveTo: date | None = None
    currency: str = Field(default="KES", min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=4000)
    #: Reviewed first, then activated. ``activate`` implies validation: it will not activate a
    #: version that fails, so the flag is a shortcut, not a way around review.
    activate: bool = False

    @model_validator(mode="after")
    def _ordered_dates(self) -> PricingVersionInput:
        if self.effectiveTo and self.effectiveTo < self.effectiveFrom:
            raise ValueError("effectiveTo must not be before effectiveFrom")
        return self


class PricingRuleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    destinationId: str
    roadTypeId: str | None = None
    vehicleId: str | None = None
    basePrice: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    label: str | None = Field(default=None, max_length=160)
    adjustmentType: AdjustmentTypeLiteral = "none"
    adjustmentValue: Decimal | None = None
    roadAdjustmentType: AdjustmentTypeLiteral = "none"
    roadAdjustmentValue: Decimal | None = None
    vehicleAdjustmentType: AdjustmentTypeLiteral = "none"
    vehicleAdjustmentValue: Decimal | None = None
    minCharge: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))
    priority: int = 0
    effectiveFrom: date | None = None
    effectiveTo: date | None = None
    active: bool = True
    notes: str | None = Field(default=None, max_length=4000)
    versionId: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PricingRuleInput:
        _require_value(self.adjustmentType, self.adjustmentValue, "adjustmentValue")
        _require_value(self.roadAdjustmentType, self.roadAdjustmentValue, "roadAdjustmentValue")
        _require_value(self.vehicleAdjustmentType, self.vehicleAdjustmentValue, "vehicleAdjustmentValue")
        if self.effectiveTo and self.effectiveFrom and self.effectiveTo < self.effectiveFrom:
            raise ValueError("effectiveTo must not be before effectiveFrom")
        return self


class PricingRuleUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=160)
    basePrice: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))
    adjustmentType: AdjustmentTypeLiteral | None = None
    adjustmentValue: Decimal | None = None
    roadAdjustmentType: AdjustmentTypeLiteral | None = None
    roadAdjustmentValue: Decimal | None = None
    vehicleAdjustmentType: AdjustmentTypeLiteral | None = None
    vehicleAdjustmentValue: Decimal | None = None
    minCharge: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))
    priority: int | None = None
    effectiveFrom: date | None = None
    effectiveTo: date | None = None
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _consistent(self) -> PricingRuleUpdate:
        if self.adjustmentType is not None:
            _require_value(self.adjustmentType, self.adjustmentValue, "adjustmentValue")
        if self.roadAdjustmentType is not None:
            _require_value(self.roadAdjustmentType, self.roadAdjustmentValue, "roadAdjustmentValue")
        if self.vehicleAdjustmentType is not None:
            _require_value(self.vehicleAdjustmentType, self.vehicleAdjustmentValue, "vehicleAdjustmentValue")
        if self.effectiveTo and self.effectiveFrom and self.effectiveTo < self.effectiveFrom:
            raise ValueError("effectiveTo must not be before effectiveFrom")
        return self


def _require_value(adjustment_type: str, value: Decimal | None, field: str) -> None:
    if adjustment_type == "none":
        return
    if value is None:
        raise ValueError(f"{field} is required when the adjustment type is '{adjustment_type}'")


class PricingImportRequest(BaseModel):
    """Import RIMs' price list from the CSV file registered in ``data/pricing``."""

    filename: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=120)
    effectiveFrom: date
    effectiveTo: date | None = None
    activate: bool = False
    dryRun: bool = True
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _ordered_dates(self) -> PricingImportRequest:
        if self.effectiveTo and self.effectiveTo < self.effectiveFrom:
            raise ValueError("effectiveTo must not be before effectiveFrom")
        return self


class PricingImportReport(BaseModel):
    dryRun: bool
    label: str
    versionId: str | None = None
    destinationCount: int = 0
    ruleCount: int = 0
    createdDestinations: list[str] = Field(default_factory=list)
    createdAliases: list[str] = Field(default_factory=list)
    createdZones: list[str] = Field(default_factory=list)
    createdRoadTypes: list[str] = Field(default_factory=list)
    createdVehicles: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class UserCreateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    fullName: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)
    role: RoleLiteral = "viewer"
    active: bool = True


class UserUpdateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    fullName: str | None = Field(default=None, min_length=1, max_length=200)
    role: RoleLiteral | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=200)


class PasswordResetRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=200)
    newPassword: str = Field(min_length=12, max_length=200)


class QuoteUpdateInput(BaseModel):
    """Staff corrections. Amounts are never editable - a quote is re-priced instead."""

    status: Literal["needs_review", "failed", "completed"] | None = None
    reviewNote: str | None = Field(default=None, max_length=1000)
    archived: bool | None = None


class HealthModel(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    environment: str
    checks: dict[str, str] = Field(default_factory=dict)


class ReadinessModel(HealthModel):
    ready: bool
    cache: str | None = None
    providers: dict[str, str] = Field(default_factory=dict)
    pricingConfigured: bool = False
    activePricingVersion: str | None = None
    destinationCount: int = 0
    timestamp: datetime | None = None


# ── admin response models ─────────────────────────────────────────────────────────
# These are the write-free counterparts of the input schemas above. Fields the frontend does
# not use yet (aliases, boundary flags, separate road/vehicle adjustments) are included because
# the admin screens are the only place an operator can see whether configuration is complete.


class MoneyOut(BaseModel):
    amount: Decimal
    currency: str = "KES"


class LatLngOut(BaseModel):
    lat: float
    lng: float


class ReferenceOut(BaseModel):
    id: str
    name: str


class ZoneModel(BaseModel):
    id: str
    name: str
    code: str
    description: str | None = None
    active: bool = True
    destinationCount: int = 0


class DestinationModel(BaseModel):
    id: str
    name: str
    code: str
    zone: str = ""
    zoneId: str | None = None
    county: str | None = None
    position: LatLngOut | None = None
    active: bool = True
    aliases: list[str] = Field(default_factory=list)
    aliasesCount: int = 0
    hasBoundary: bool = False
    catchmentRadiusKm: Decimal | None = None
    currentBasePrice: MoneyOut | None = None


class PricingRuleModel(BaseModel):
    id: str
    versionId: str
    versionLabel: str | None = None
    versionStatus: str | None = None
    destinationId: str
    destinationName: str | None = None
    roadTypeId: str | None = None
    roadTypeName: str | None = None
    vehicleId: str | None = None
    vehicleName: str | None = None
    label: str | None = None
    basePrice: Decimal
    adjustmentType: AdjustmentTypeLiteral
    adjustmentValue: Decimal | None = None
    roadAdjustmentType: AdjustmentTypeLiteral
    roadAdjustmentValue: Decimal | None = None
    vehicleAdjustmentType: AdjustmentTypeLiteral
    vehicleAdjustmentValue: Decimal | None = None
    minCharge: Decimal | None = None
    priority: int = 0
    effectiveFrom: str
    effectiveTo: str | None = None
    active: bool = True
    notes: str | None = None


class PricingVersionModel(BaseModel):
    id: str
    label: str
    status: str
    effectiveFrom: str
    effectiveTo: str | None = None
    currency: str = "KES"
    notes: str | None = None
    source: str | None = None
    ruleCount: int = 0
    destinationCount: int = 0
    createdAt: datetime
    activatedAt: datetime | None = None
    #: When an administrator last reviewed this version and it passed validation.
    validatedAt: datetime | None = None
    validatedBy: str | None = None
    validationNote: str | None = None


class RoadSegmentModel(BaseModel):
    id: str
    name: str
    roadTypeId: str
    roadTypeName: str | None = None
    destinationId: str | None = None
    position: LatLngOut
    radiusKm: Decimal
    confirmed: bool = False
    active: bool = True


class OriginModel(BaseModel):
    id: str
    name: str
    position: LatLngOut
    isDefault: bool = False
    active: bool = True


class ActivationResult(BaseModel):
    """Outcome of activating a pricing version, including what it retired."""

    versionId: str
    label: str
    activatedAt: datetime
    retiredVersionId: str | None = None
    retiredLabel: str | None = None
    ruleCount: int = 0


class ValidationFinding(BaseModel):
    """One problem, warning or review item found in a pricing version.

    ``severity`` is ``error`` (blocks activation) or ``warning`` (activatable, but an
    administrator should confirm the detail first).
    """

    code: str
    severity: Literal["error", "warning"]
    message: str
    destinationName: str | None = None
    ruleId: str | None = None


class VersionValidationResult(BaseModel):
    """Verdict for a pricing version: safe to activate, or blocked with findings.

    Deliberately carries no ``checkedAt``: validation re-runs on every activation, so a stored
    timestamp would only ever invite someone to trust a stale verdict.
    """

    versionId: str
    label: str
    status: str
    valid: bool
    ruleCount: int = 0
    destinationCount: int = 0
    findings: list[ValidationFinding] = Field(default_factory=list)
    summary: str


# ── distance-based ("dynamic") pricing ──────────────────────────────────────────────
#
# Model B. These schemas configure a rate per kilometre; they never touch the fixed
# destination price list, and activating one never retires a fixed pricing version.

PricingStatusLiteral = Literal["draft", "active", "retired"]


class DynamicPricingInput(BaseModel):
    """A new distance-rate configuration, created as a draft until an admin activates it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)
    baseRatePerKm: Decimal = Field(gt=0, le=Decimal("9999999999.99"))
    fuelAdjustmentPercent: Decimal = Field(
        default=Decimal("0"), ge=Decimal("-100"), le=Decimal("1000")
    )
    minCharge: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))
    currency: str = Field(default="KES", min_length=3, max_length=3)
    effectiveFrom: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)


class DynamicPricingUpdate(BaseModel):
    """Partial edit. Only a draft or a retired configuration may be changed - see the router."""

    label: str | None = Field(default=None, min_length=1, max_length=120)
    baseRatePerKm: Decimal | None = Field(default=None, gt=0, le=Decimal("9999999999.99"))
    fuelAdjustmentPercent: Decimal | None = Field(
        default=None, ge=Decimal("-100"), le=Decimal("1000")
    )
    minCharge: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    effectiveFrom: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)


class DynamicPricingModel(BaseModel):
    id: str
    label: str
    status: PricingStatusLiteral
    baseRatePerKm: Decimal
    fuelAdjustmentPercent: Decimal
    minCharge: Decimal | None = None
    currency: str = "KES"
    #: The rate customers are actually charged once the fuel adjustment is applied.
    effectiveRatePerKm: Decimal
    effectiveFrom: datetime | None = None
    notes: str | None = None
    createdAt: datetime
    activatedAt: datetime | None = None
    retiredAt: datetime | None = None
    createdBy: str | None = None


class DynamicPricingActivation(BaseModel):
    """What activating a distance-rate configuration did, including what it retired."""

    versionId: str
    label: str
    activatedAt: datetime
    retiredVersionId: str | None = None
    retiredLabel: str | None = None


class DynamicPricingPreviewRequest(BaseModel):
    """Ask the real pricing engine what a given road distance costs under model B.

    Optional field overrides let an admin try a rate before saving it; with no overrides the
    preview uses the stored configuration named by ``versionId``, else the active one.
    """

    distanceKm: Decimal = Field(gt=0, le=Decimal("10000"))
    versionId: str | None = None
    baseRatePerKm: Decimal | None = Field(default=None, gt=0, le=Decimal("9999999999.99"))
    fuelAdjustmentPercent: Decimal | None = Field(
        default=None, ge=Decimal("-100"), le=Decimal("1000")
    )
    minCharge: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999999.99"))


class DynamicPricingPreviewAdjustment(BaseModel):
    """One labelled line of the previewed amount, exactly as the engine applied it."""

    label: str
    amount: Decimal
    kind: str | None = None
    detail: str | None = None


class DynamicPricingPreviewResult(BaseModel):
    """The engine's answer, not a frontend re-implementation of it."""

    priced: bool
    distanceKm: Decimal
    currency: str = "KES"
    configLabel: str | None = None
    configId: str | None = None
    baseRatePerKm: Decimal | None = None
    fuelAdjustmentPercent: Decimal | None = None
    effectiveRatePerKm: Decimal | None = None
    total: Decimal | None = None
    adjustments: list[DynamicPricingPreviewAdjustment] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    #: Present only when the engine refused (no configuration, missing distance, ...).
    reason: str | None = None
    message: str | None = None
