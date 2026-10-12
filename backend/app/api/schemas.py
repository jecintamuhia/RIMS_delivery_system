"""Shared response primitives.

These mirror ``rims-delivery-ui/src/types/index.ts`` field for field. That file is the contract;
when it changes, these change with it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models import QuoteStatus, StepKey, StepState

T = TypeVar("T")


class LatLngModel(BaseModel):
    lat: float
    lng: float


class MoneyModel(BaseModel):
    amount: Decimal
    currency: str = "KES"


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """The envelope the frontend parses in ``client.ts``."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    pageSize: int = Field(validation_alias="pageSize")


class ReferenceModel(BaseModel):
    id: str
    name: str


class RoadTypeModel(BaseModel):
    id: str
    name: str
    code: str
    description: str | None = None
    condition: str = "unclassified"
    active: bool = True


class VehicleCategoryModel(BaseModel):
    id: str
    name: str
    code: str
    description: str | None = None
    maxWeightKg: Decimal | None = None
    maxVolumeM3: Decimal | None = None
    sortOrder: int = 0
    active: bool = True


class CompanyModel(BaseModel):
    name: str
    logoUrl: str | None = None
    contactPhone: str | None = None
    contactEmail: str | None = None


class DispatchModel(BaseModel):
    """The RIMs dispatch point. Coordinates are bounds-checked: a depot outside Kenya would
    silently mis-route every delivery."""

    name: str = Field(min_length=1, max_length=160)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class MapDefaultsModel(BaseModel):
    center: LatLngModel
    zoom: int
    tileUrl: str | None = None
    attribution: str | None = None


class PublicConfig(BaseModel):
    company: CompanyModel
    dispatch: DispatchModel
    map: MapDefaultsModel


class GeoLocationModel(BaseModel):
    id: str
    label: str
    secondary: str | None = None
    position: LatLngModel


class RouteModel(BaseModel):
    summary: str | None = None
    geometry: list[LatLngModel] | None = None


class RoutePreviewModel(BaseModel):
    """Road distance and travel time from RIMs' dispatch point to a pinned location.

    Returned by the locate step so the map can show how far the delivery is *before* a quote
    exists. Carries no price: pricing still happens once, in the quote pipeline.
    """

    distanceKm: Decimal
    durationMinutes: int
    route: RouteModel | None = None


class QuoteStepModel(BaseModel):
    key: StepKey
    state: StepState


class QuoteFailureModel(BaseModel):
    code: str
    message: str | None = None
    candidates: list[GeoLocationModel] | None = None


class QuoteModel(BaseModel):
    """Customer-facing quote. Deliberately contains no internal pricing breakdown."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    reference: str | None = None
    status: QuoteStatus
    steps: list[QuoteStepModel]
    createdAt: datetime
    location: QuoteLocationModel
    dispatch: DispatchModel | None = None
    destination: ReferenceModel | None = None
    distanceKm: Decimal | None = None
    durationMinutes: int | None = None
    route: RouteModel | None = None
    roadType: ReferenceModel | None = None
    vehicle: ReferenceModel | None = None
    fee: MoneyModel | None = None
    #: ``fixed_destination`` (RIMs' official destination price) or ``distance_based``
    #: (road distance x the configured rate). Never omitted once a fee exists.
    pricingModel: str | None = None
    #: One customer-readable sentence explaining how the fee was calculated.
    pricingExplanation: str | None = None
    failure: QuoteFailureModel | None = None


class QuoteLocationModel(BaseModel):
    label: str
    secondary: str | None = None
    position: LatLngModel


class QuoteAdjustmentModel(BaseModel):
    label: str
    amount: MoneyModel
    kind: str | None = None
    detail: str | None = None


class QuoteBreakdownModel(BaseModel):
    basePrice: MoneyModel
    adjustments: list[QuoteAdjustmentModel]
    ruleId: str | None = None
    ruleLabel: str | None = None
    pricingVersion: str | None = None
    pricingModel: str | None = None
    #: Audit record for a distance-based amount: distance, rates, fuel adjustment, total.
    pricingDetails: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


class AdminQuoteModel(QuoteModel):
    """Admin view: adds the calculation breakdown and operational fields."""

    customerReference: str | None = None
    destinationMatchMethod: str | None = None
    routingProvider: str | None = None
    attemptCount: int = 0
    acceptedAt: datetime | None = None
    breakdown: QuoteBreakdownModel | None = None
    calculations: list[QuoteCalculationModel] = Field(default_factory=list)


class QuoteCalculationModel(BaseModel):
    id: str
    createdAt: datetime
    basePrice: MoneyModel
    total: MoneyModel
    ruleId: str | None = None
    ruleLabel: str | None = None
    pricingVersion: str | None = None
    pricingModel: str | None = None
    pricingDetails: dict[str, Any] | None = None
    adjustments: list[QuoteAdjustmentModel] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QuoteListItemModel(QuoteModel):
    destinationName: str | None = None


class CreateQuoteRequest(BaseModel):
    position: LatLngModel
    label: str = Field(min_length=1, max_length=320)
    locationId: str | None = Field(default=None, max_length=160)
    reference: str | None = Field(default=None, max_length=120)
    loadWeightKg: Decimal | None = Field(default=None, ge=0, le=100_000)
    loadVolumeM3: Decimal | None = Field(default=None, ge=0, le=1_000)
    #: Skip the reverse-geocode lookup when the customer already chose a resolved place.
    resolved: bool = False


class DashboardSummaryModel(BaseModel):
    quotesToday: int
    quotesThisWeek: int
    totalQuotedValue: MoneyModel
    averageDistanceKm: Decimal | None = None
    topDestinations: list[TopDestinationModel] = Field(default_factory=list)
    needsReview: list[NeedsReviewModel] = Field(default_factory=list)
    statusCounts: dict[str, int] = Field(default_factory=dict)


class TopDestinationModel(BaseModel):
    name: str
    count: int
    value: MoneyModel | None = None


class NeedsReviewModel(BaseModel):
    id: str
    locationLabel: str
    reason: str | None = None
    createdAt: datetime


class AppSettingsModel(BaseModel):
    dispatch: DispatchModel
    contactPhone: str | None = None
    contactEmail: str | None = None
    activePricingVersion: str | None = None
    mapProvider: str | None = None
    defaultRoadType: ReferenceModel | None = None
    defaultVehicle: ReferenceModel | None = None
    requiresRoadType: bool = False
    requiresVehicle: bool = False
    destinationCount: int = 0
    activeRuleCount: int = 0


class UpdateSettingsRequest(BaseModel):
    dispatch: DispatchModel | None = None
    contactPhone: str | None = Field(default=None, max_length=60)
    contactEmail: str | None = Field(default=None, max_length=320)
    defaultOriginId: str | None = None
    defaultRoadTypeId: str | None = None
    defaultVehicleId: str | None = None
    activePricingVersionId: str | None = None


class AdminUserModel(BaseModel):
    id: str
    name: str
    email: str
    role: Literal["admin", "editor", "viewer"]
    isActive: bool = True
    lastLoginAt: datetime | None = None
    createdAt: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class AuditEntryModel(BaseModel):
    id: str
    at: datetime
    actor: str
    action: str
    entityType: str
    entityId: str | None = None
    summary: str


QuoteModel.model_rebuild()
AdminQuoteModel.model_rebuild()
QuoteCalculationModel.model_rebuild()
DashboardSummaryModel.model_rebuild()
