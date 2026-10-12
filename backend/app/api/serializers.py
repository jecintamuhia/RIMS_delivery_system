"""ORM -> API translation.

Kept in one module so the wire format is decided in a single place and the routers stay thin.
Field names here match ``rims-delivery-ui/src/types/index.ts`` exactly.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.api.schemas import (
    AdminQuoteModel,
    AdminUserModel,
    AppSettingsModel,
    AuditEntryModel,
    CompanyModel,
    DispatchModel,
    GeoLocationModel,
    LatLngModel,
    MapDefaultsModel,
    MoneyModel,
    PublicConfig,
    QuoteAdjustmentModel,
    QuoteBreakdownModel,
    QuoteCalculationModel,
    QuoteFailureModel,
    QuoteListItemModel,
    QuoteLocationModel,
    QuoteModel,
    QuoteStepModel,
    ReferenceModel,
    RoadTypeModel,
    RouteModel,
    VehicleCategoryModel,
)
from app.models import (
    STEP_ORDER,
    AdjustmentType,
    AuditLog,
    DeliveryOrigin,
    Destination,
    PricingVersion,
    Quote,
    QuoteCalculation,
    RoadType,
    StepState,
    User,
    VehicleCategory,
)


def money(amount: Decimal | None, currency: str = "KES") -> MoneyModel | None:
    if amount is None:
        return None
    return MoneyModel(amount=Decimal(amount), currency=currency)


def money_required(amount: Decimal, currency: str = "KES") -> MoneyModel:
    return MoneyModel(amount=Decimal(amount), currency=currency)


def reference(obj: Any) -> ReferenceModel | None:
    if obj is None:
        return None
    return ReferenceModel(id=obj.id, name=obj.name)


def dispatch_model(origin: DeliveryOrigin | None, fallback_name: str = "RIMs dispatch") -> DispatchModel | None:
    if origin is None:
        return None
    return DispatchModel(name=origin.name, lat=origin.latitude, lng=origin.longitude)


def steps_model(steps: list[dict[str, str]] | None) -> list[QuoteStepModel]:
    """Normalise step state onto the canonical order.

    A missing or malformed step is reported as ``pending`` rather than omitted, so the customer
    always sees the same five stages and nothing appears finished that is not.
    """
    by_key = {str(entry.get("key")): str(entry.get("state")) for entry in (steps or []) if isinstance(entry, dict)}
    out: list[QuoteStepModel] = []
    for step in STEP_ORDER:
        raw_state = by_key.get(step.value, StepState.PENDING.value)
        try:
            state = StepState(raw_state)
        except ValueError:
            state = StepState.PENDING
        out.append(QuoteStepModel(key=step, state=state))
    return out


def route_model(geometry_json: Any) -> RouteModel | None:
    if not geometry_json:
        return None
    return RouteModel(geometry=[LatLngModel(lat=p[0], lng=p[1]) for p in geometry_json])


def failure_model(quote: Quote) -> QuoteFailureModel | None:
    if not quote.failure_code:
        return None
    return QuoteFailureModel(code=quote.failure_code, message=quote.failure_message)


def _latest_calculation(quote: Quote) -> QuoteCalculation | None:
    return quote.calculations[0] if quote.calculations else None


def calculation_model(calculation: QuoteCalculation) -> QuoteCalculationModel:
    adjustments = [
        QuoteAdjustmentModel(
            label=str(entry.get("label", "")),
            amount=MoneyModel(amount=Decimal(str(entry.get("amount", "0"))), currency=calculation.currency),
            kind=entry.get("kind"),
            detail=entry.get("detail"),
        )
        for entry in (calculation.breakdown or [])
        if isinstance(entry, dict)
    ]
    return QuoteCalculationModel(
        id=calculation.id,
        createdAt=calculation.created_at,
        basePrice=MoneyModel(amount=Decimal(calculation.base_price), currency=calculation.currency),
        total=MoneyModel(amount=Decimal(calculation.total_amount), currency=calculation.currency),
        ruleId=calculation.rule_id,
        ruleLabel=calculation.rule_label,
        pricingVersion=calculation.pricing_version_label
        or (calculation.pricing_details or {}).get("configLabel"),
        pricingModel=calculation.pricing_model,
        pricingDetails=calculation.pricing_details or None,
        adjustments=adjustments,
        notes=list(calculation.notes or []),
    )


def _money(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(value):.2f}"


def _pricing_explanation(quote: Quote, calculation: QuoteCalculation | None) -> str | None:
    """One customer-readable sentence a person can check against the numbers on screen.

    Never hides the model that produced the amount: a distance-based quote states the road
    distance, the effective rate and the fuel adjustment; a fixed quote names the official
    RIMs destination price it came from.
    """
    if calculation is None or quote.fee_amount is None:
        return None
    currency = calculation.currency
    if calculation.pricing_model == "distance_based":
        details = calculation.pricing_details or {}
        distance = details.get("distanceKm")
        base_rate = details.get("baseRatePerKm")
        effective = details.get("effectiveRatePerKm")
        percent = details.get("fuelAdjustmentPercent")
        if distance and effective:
            line = f"Road distance {distance} km x {currency} {effective}/km"
            if base_rate and percent not in (None, "", "0", "0.00"):
                line += f" (base {currency} {base_rate}/km, {percent}% fuel adjustment)"
            return f"{line} = {currency} {_money(calculation.total_amount)}."
        return f"Distance-based delivery: {currency} {_money(calculation.total_amount)}."
    destination = quote.destination
    name = destination.name if destination is not None else "this delivery location"
    return f"Official RIMs price for {name}: {currency} {_money(calculation.total_amount)}."


def quote_model(quote: Quote) -> QuoteModel:
    """Customer-facing view. Never includes the pricing breakdown."""
    calculation = _latest_calculation(quote)
    return QuoteModel(
        id=quote.id,
        reference=quote.customer_reference,
        status=quote.status,
        steps=steps_model(quote.steps),
        createdAt=quote.created_at,
        location=QuoteLocationModel(
            label=quote.resolved_label or quote.input_label,
            secondary=quote.resolved_secondary,
            position=LatLngModel(
            lat=quote.latitude or quote.input_latitude, lng=quote.longitude or quote.input_longitude
        ),
        ),
        dispatch=dispatch_model(quote.origin),
        destination=reference(quote.destination),
        distanceKm=Decimal(quote.route_distance_km) if quote.route_distance_km is not None else None,
        durationMinutes=(
            round(quote.route_duration_seconds / 60) if quote.route_duration_seconds is not None else None
        ),
        route=route_model(quote.route_geometry),
        roadType=reference(quote.road_type),
        vehicle=reference(quote.vehicle),
        fee=money(quote.fee_amount, quote.currency),
        pricingModel=quote.pricing_model,
        pricingExplanation=_pricing_explanation(quote, calculation),
        failure=failure_model(quote),
    )


def admin_quote_model(quote: Quote) -> AdminQuoteModel:
    calculation = _latest_calculation(quote)
    breakdown: QuoteBreakdownModel | None = None
    if calculation is not None:
        breakdown = QuoteBreakdownModel(
            basePrice=MoneyModel(
                amount=Decimal(calculation.base_price), currency=calculation.currency
            ),
            adjustments=[
                QuoteAdjustmentModel(
                    label=str(entry.get("label", "")),
                    amount=MoneyModel(
                        amount=Decimal(str(entry.get("amount", "0"))), currency=calculation.currency
                    ),
                    kind=entry.get("kind"),
                    detail=entry.get("detail"),
                )
                for entry in (calculation.breakdown or [])
                if isinstance(entry, dict)
            ],
            ruleId=calculation.rule_id,
            ruleLabel=calculation.rule_label,
            pricingVersion=calculation.pricing_version_label
            if calculation.pricing_model != "distance_based"
            else (calculation.pricing_details or {}).get("configLabel"),
            pricingModel=calculation.pricing_model,
            pricingDetails=calculation.pricing_details or None,
            notes=list(calculation.notes or []),
        )
    return AdminQuoteModel(
        **quote_model(quote).model_dump(),
        customerReference=quote.customer_reference,
        destinationMatchMethod=quote.destination_match_method,
        routingProvider=quote.routing_provider,
        attemptCount=quote.attempt_count,
        acceptedAt=quote.accepted_at,
        breakdown=breakdown,
        calculations=[calculation_model(item) for item in quote.calculations],
    )


def quote_list_item(quote: Quote) -> QuoteListItemModel:
    return QuoteListItemModel(
        **quote_model(quote).model_dump(),
        destinationName=quote.destination.name if quote.destination else None,
    )


def destination_model(destination: Destination, current_base_price: Decimal | None) -> dict[str, Any]:
    return {
        "id": destination.id,
        "name": destination.name,
        "code": destination.code,
        "zone": destination.zone.name if destination.zone else "",
        "zoneId": destination.zone_id,
        "county": destination.county,
        "position": (
            LatLngModel(lat=destination.latitude, lng=destination.longitude)
            if destination.latitude is not None and destination.longitude is not None
            else None
        ),
        "active": destination.is_active,
        "aliases": [alias.alias for alias in destination.aliases],
        "aliasesCount": len(destination.aliases),
        "hasBoundary": destination.boundary is not None,
        "catchmentRadiusKm": (
            Decimal(destination.catchment_radius_km) if destination.catchment_radius_km is not None else None
        ),
        "currentBasePrice": money(current_base_price),
    }


def road_type_model(road_type: RoadType) -> RoadTypeModel:
    return RoadTypeModel(
        id=road_type.id,
        name=road_type.name,
        code=road_type.code,
        description=road_type.description,
        condition=road_type.condition.value,
        active=road_type.is_active,
    )


def vehicle_model(vehicle: VehicleCategory) -> VehicleCategoryModel:
    return VehicleCategoryModel(
        id=vehicle.id,
        name=vehicle.name,
        code=vehicle.code,
        description=vehicle.description,
        maxWeightKg=Decimal(vehicle.max_weight_kg) if vehicle.max_weight_kg is not None else None,
        maxVolumeM3=Decimal(vehicle.max_volume_m3) if vehicle.max_volume_m3 is not None else None,
        sortOrder=vehicle.sort_order,
        active=vehicle.is_active,
    )


def pricing_rule_model(rule: Any, version: PricingVersion | None = None) -> dict[str, Any]:
    return {
        "id": rule.id,
        "versionId": rule.version_id,
        "versionLabel": version.label if version else None,
        "versionStatus": version.status.value if version else None,
        "destinationId": rule.destination_id,
        "destinationName": rule.destination.name if rule.destination else None,
        "roadTypeId": rule.road_type_id,
        "roadTypeName": rule.road_type.name if rule.road_type else None,
        "vehicleId": rule.vehicle_id,
        "vehicleName": rule.vehicle.name if rule.vehicle else None,
        "label": rule.label,
        "basePrice": Decimal(rule.base_price),
        "adjustmentType": _enum_value(rule.adjustment_type),
        "adjustmentValue": Decimal(rule.adjustment_value) if rule.adjustment_value is not None else None,
        "roadAdjustmentType": _enum_value(rule.road_adjustment_type),
        "roadAdjustmentValue": Decimal(rule.road_adjustment_value)
        if rule.road_adjustment_value is not None
        else None,
        "vehicleAdjustmentType": _enum_value(rule.vehicle_adjustment_type),
        "vehicleAdjustmentValue": Decimal(rule.vehicle_adjustment_value)
        if rule.vehicle_adjustment_value is not None
        else None,
        "minCharge": Decimal(rule.min_charge) if rule.min_charge is not None else None,
        "priority": rule.priority,
        "effectiveFrom": _iso(rule.effective_from),
        "effectiveTo": _iso(rule.effective_to),
        "active": rule.is_active,
        "notes": rule.notes,
    }


def _enum_value(value: object) -> str:
    if isinstance(value, AdjustmentType):
        return value.value
    return str(value)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def pricing_version_model(version: PricingVersion, rule_count: int | None = None) -> dict[str, Any]:
    return {
        "id": version.id,
        "label": version.label,
        "status": version.status.value,
        "effectiveFrom": _iso(version.effective_from),
        "effectiveTo": _iso(version.effective_to),
        "currency": version.currency,
        "notes": version.notes,
        "source": version.source,
        "ruleCount": rule_count if rule_count is not None else len(version.rules),
        "destinationCount": len({rule.destination_id for rule in version.rules}),
        "createdAt": version.created_at,
        "activatedAt": version.activated_at,
        "validatedAt": version.validated_at,
        "validatedBy": version.validated_by_id,
        "validationNote": version.validation_note,
    }


def audit_model(entry: AuditLog) -> AuditEntryModel:
    return AuditEntryModel(
        id=entry.id,
        at=entry.created_at,
        actor=entry.actor_label,
        action=entry.action,
        entityType=entry.entity_type,
        entityId=entry.entity_id,
        summary=entry.summary,
    )


def user_model(user: User) -> AdminUserModel:
    return AdminUserModel(
        id=user.id,
        name=user.full_name,
        email=user.email,
        role=user.role.value,
        isActive=user.is_active,
        lastLoginAt=user.last_login_at,
        createdAt=user.created_at,
    )


def public_config_model(
    *,
    company_name: str,
    logo_url: str | None,
    contact_phone: str | None,
    contact_email: str | None,
    origin: DeliveryOrigin | None,
    map_center_lat: float,
    map_center_lng: float,
    map_zoom: int,
    tile_url: str | None,
    attribution: str | None,
) -> PublicConfig:
    return PublicConfig(
        company=CompanyModel(
            name=company_name,
            logoUrl=logo_url,
            contactPhone=contact_phone,
            contactEmail=contact_email,
        ),
        dispatch=DispatchModel(
            name=origin.name if origin else "RIMs dispatch",
            lat=origin.latitude if origin else map_center_lat,
            lng=origin.longitude if origin else map_center_lng,
        ),
        map=MapDefaultsModel(
            center=LatLngModel(lat=map_center_lat, lng=map_center_lng),
            zoom=map_zoom,
            tileUrl=tile_url,
            attribution=attribution,
        ),
    )


def settings_model(
    *,
    origin: DeliveryOrigin | None,
    contact_phone: str | None,
    contact_email: str | None,
    active_version: PricingVersion | None,
    map_provider: str | None,
    default_road_type: RoadType | None,
    default_vehicle: VehicleCategory | None,
    requires_road_type: bool,
    requires_vehicle: bool,
    destination_count: int,
    active_rule_count: int,
) -> AppSettingsModel:
    return AppSettingsModel(
        dispatch=DispatchModel(
            name=origin.name if origin else "RIMs dispatch",
            lat=origin.latitude if origin else 0.0,
            lng=origin.longitude if origin else 0.0,
        ),
        contactPhone=contact_phone,
        contactEmail=contact_email,
        activePricingVersion=active_version.label if active_version else None,
        mapProvider=map_provider,
        defaultRoadType=reference(default_road_type),
        defaultVehicle=reference(default_vehicle),
        requiresRoadType=requires_road_type,
        requiresVehicle=requires_vehicle,
        destinationCount=destination_count,
        activeRuleCount=active_rule_count,
    )


def geo_location_model(location_id: str, label: str, secondary: str | None, lat: float, lng: float) -> GeoLocationModel:
    return GeoLocationModel(
        id=location_id, label=label, secondary=secondary, position=LatLngModel(lat=lat, lng=lng)
    )


__all__ = [
    "admin_quote_model",
    "audit_model",
    "calculation_model",
    "destination_model",
    "dispatch_model",
    "failure_model",
    "geo_location_model",
    "money",
    "money_required",
    "pricing_rule_model",
    "pricing_version_model",
    "public_config_model",
    "quote_list_item",
    "quote_model",
    "reference",
    "road_type_model",
    "settings_model",
    "steps_model",
    "user_model",
    "vehicle_model",
]
