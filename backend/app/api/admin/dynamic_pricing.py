"""Distance-based ("dynamic") pricing configuration - model B.

The system quotes two ways, and this router owns the second one:

* **Model A** (``pricing.py``): RIMs' official fixed price for a destination.
* **Model B** (here): road distance x a configured, versioned rate per kilometre.

The two are kept apart on purpose. Creating, editing, activating or retiring a distance rate
never touches a fixed pricing version, activating one never retires a price list, and a change
to the fuel adjustment never rewrites a price a customer has already been quoted - historical
quotes keep the id of the configuration they were priced with.

Only one configuration is active at a time, an active one is immutable, and previews go
through the real pricing engine rather than a second implementation of the arithmetic in the
browser.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.admin_common import audit, diff_fields, ensure_unique, translate_integrity_error
from app.api.admin_schemas import (
    DynamicPricingActivation,
    DynamicPricingInput,
    DynamicPricingModel,
    DynamicPricingPreviewAdjustment,
    DynamicPricingPreviewRequest,
    DynamicPricingPreviewResult,
    DynamicPricingUpdate,
)
from app.api.deps import AdminWriter, EditorWriter, RequireViewer, SessionDep
from app.errors import AppError, ErrorCode, not_found
from app.models import DynamicPricingVersion, PricingVersionStatus
from app.services.pricing import engine
from app.services.pricing.models import DynamicPricingConfig, PricingContext
from app.services.pricing.repository import load_active_dynamic_pricing, to_dynamic_config

logger = logging.getLogger("app.api.admin.dynamic_pricing")

router = APIRouter(prefix="/admin", tags=["admin"])


def _out(row: DynamicPricingVersion) -> DynamicPricingModel:
    config = to_dynamic_config(row)
    return DynamicPricingModel(
        id=row.id,
        label=row.label,
        status=row.status.value,
        baseRatePerKm=config.base_rate_per_km,
        fuelAdjustmentPercent=config.fuel_adjustment_percent,
        minCharge=config.min_charge,
        currency=config.currency,
        effectiveRatePerKm=config.effective_rate_per_km,
        effectiveFrom=row.effective_from,
        notes=row.notes,
        createdAt=row.created_at,
        activatedAt=row.activated_at,
        retiredAt=row.retired_at,
        createdBy=row.created_by_id,
    )


async def _load(session: SessionDep, version_id: str) -> DynamicPricingVersion:
    row = await session.get(DynamicPricingVersion, version_id)
    if row is None:
        raise not_found("Distance pricing configuration", version_id)
    return row


# ── read ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/dynamic-pricing",
    response_model=list[DynamicPricingModel],
    summary="List distance pricing configurations",
)
async def list_configurations(
    session: SessionDep,
    _: RequireViewer,
) -> list[DynamicPricingModel]:
    rows = (
        await session.scalars(
            select(DynamicPricingVersion).order_by(DynamicPricingVersion.created_at.desc())
        )
    ).all()
    return [_out(row) for row in rows]


@router.get(
    "/dynamic-pricing/active",
    response_model=DynamicPricingModel | None,
    summary="Read the active distance pricing configuration",
)
async def get_active(session: SessionDep, _: RequireViewer) -> DynamicPricingModel | None:
    """``null`` means distance-based pricing is switched off - not that a rate defaults to 0."""
    row = await session.scalar(
        select(DynamicPricingVersion)
        .where(DynamicPricingVersion.status == PricingVersionStatus.ACTIVE)
        .limit(1)
    )
    return _out(row) if row is not None else None


# ── write ───────────────────────────────────────────────────────────────────────────


@router.post(
    "/dynamic-pricing",
    response_model=DynamicPricingModel,
    status_code=201,
    summary="Create a distance pricing configuration",
)
async def create_configuration(
    payload: DynamicPricingInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> DynamicPricingModel:
    """Created as a draft. Nothing is charged at this rate until an admin activates it."""
    await ensure_unique(session, "dynamic_pricing_version", "label", payload.label)
    row = DynamicPricingVersion(
        label=payload.label,
        status=PricingVersionStatus.DRAFT,
        base_rate_per_km=payload.baseRatePerKm,
        fuel_adjustment_percent=payload.fuelAdjustmentPercent,
        min_charge=payload.minCharge,
        currency=payload.currency.upper(),
        effective_from=payload.effectiveFrom,
        notes=payload.notes,
        created_by_id=actor.user.id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise translate_integrity_error(exc) from exc
    await audit(
        session,
        request,
        action="created",
        entity_type="dynamic_pricing_version",
        entity_id=row.id,
        entity_label=row.label,
        summary=f"Created distance pricing configuration “{row.label}”",
        changes={
            "baseRatePerKm": str(row.base_rate_per_km),
            "fuelAdjustmentPercent": str(row.fuel_adjustment_percent),
            "minCharge": str(row.min_charge) if row.min_charge is not None else None,
        },
        actor=actor.user,
    )
    await session.commit()
    logger.info("dynamic pricing configuration created: %s", row.label)
    return _out(row)


@router.patch(
    "/dynamic-pricing/{version_id}",
    response_model=DynamicPricingModel,
    summary="Update a distance pricing configuration",
)
async def update_configuration(
    version_id: str,
    payload: DynamicPricingUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> DynamicPricingModel:
    row = await _load(session, version_id)
    if row.status is PricingVersionStatus.ACTIVE:
        # Same invariant as the fixed price list: live rates change by activating a new
        # configuration, never by editing the one customers are being priced with.
        raise AppError(
            ErrorCode.VALIDATION,
            "This configuration is active, so it cannot be edited. Create a new one and "
            "activate it instead - a quote already issued must keep the rate it was priced with.",
        )

    before = {
        "label": row.label,
        "baseRatePerKm": str(row.base_rate_per_km),
        "fuelAdjustmentPercent": str(row.fuel_adjustment_percent),
        "minCharge": str(row.min_charge) if row.min_charge is not None else None,
        "currency": row.currency,
        "notes": row.notes,
    }
    if payload.label is not None and payload.label != row.label:
        await ensure_unique(
            session, "dynamic_pricing_version", "label", payload.label, exclude_id=row.id
        )
        row.label = payload.label
    if payload.baseRatePerKm is not None:
        row.base_rate_per_km = payload.baseRatePerKm
    if payload.fuelAdjustmentPercent is not None:
        row.fuel_adjustment_percent = payload.fuelAdjustmentPercent
    if payload.minCharge is not None:
        row.min_charge = payload.minCharge
    if payload.currency is not None:
        row.currency = payload.currency.upper()
    if payload.effectiveFrom is not None:
        row.effective_from = payload.effectiveFrom
    if payload.notes is not None:
        row.notes = payload.notes

    after = {
        "label": row.label,
        "baseRatePerKm": str(row.base_rate_per_km),
        "fuelAdjustmentPercent": str(row.fuel_adjustment_percent),
        "minCharge": str(row.min_charge) if row.min_charge is not None else None,
        "currency": row.currency,
        "notes": row.notes,
    }
    changes = diff_fields(before, after)
    await audit(
        session,
        request,
        action="updated",
        entity_type="dynamic_pricing_version",
        entity_id=row.id,
        entity_label=row.label,
        summary=f"Updated distance pricing configuration “{row.label}”",
        changes=changes,
        actor=actor.user,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        raise translate_integrity_error(exc) from exc
    return _out(row)


@router.post(
    "/dynamic-pricing/{version_id}/activate",
    response_model=DynamicPricingActivation,
    summary="Activate a distance pricing configuration",
)
async def activate_configuration(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> DynamicPricingActivation:
    """Make this the rate distance-based quotes are priced with, retiring the previous one.

    Retiring and activating happen in one transaction, so there is never a moment with two
    active rates - or none - for a quote to land on.
    """
    row = await _load(session, version_id)
    now = datetime.now(UTC)
    if row.status is PricingVersionStatus.ACTIVE:
        # Idempotent: a retried activation must not look like a second activation.
        return DynamicPricingActivation(
            versionId=row.id,
            label=row.label,
            activatedAt=row.activated_at or now,
        )

    previous = await session.scalar(
        select(DynamicPricingVersion)
        .where(DynamicPricingVersion.status == PricingVersionStatus.ACTIVE)
        .limit(1)
    )
    retired_id = retired_label = None
    if previous is not None and previous.id != row.id:
        previous.status = PricingVersionStatus.RETIRED
        previous.retired_at = now
        retired_id, retired_label = previous.id, previous.label

    row.status = PricingVersionStatus.ACTIVE
    row.activated_at = now
    row.retired_at = None

    await audit(
        session,
        request,
        action="activated",
        entity_type="dynamic_pricing_version",
        entity_id=row.id,
        entity_label=row.label,
        summary=f"Activated distance pricing configuration “{row.label}”",
        changes={
            "baseRatePerKm": str(row.base_rate_per_km),
            "fuelAdjustmentPercent": str(row.fuel_adjustment_percent),
            "retired": retired_label,
        },
        actor=actor.user,
    )
    await session.commit()
    logger.info(
        "dynamic pricing activated: %s (retired=%s)", row.label, retired_label or "none"
    )
    return DynamicPricingActivation(
        versionId=row.id,
        label=row.label,
        activatedAt=now,
        retiredVersionId=retired_id,
        retiredLabel=retired_label,
    )


@router.post(
    "/dynamic-pricing/{version_id}/retire",
    response_model=DynamicPricingModel,
    summary="Switch distance-based pricing off",
)
async def retire_configuration(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> DynamicPricingModel:
    """Turn dynamic pricing off entirely.

    With nothing active, a location outside the official price list is refused honestly
    rather than priced at a rate nobody configured.
    """
    row = await _load(session, version_id)
    if row.status is not PricingVersionStatus.ACTIVE:
        raise AppError(
            ErrorCode.VALIDATION,
            "Only the active distance pricing configuration can be retired. "
            "Delete or edit this draft instead.",
        )
    now = datetime.now(UTC)
    row.status = PricingVersionStatus.RETIRED
    row.retired_at = now
    await audit(
        session,
        request,
        action="retired",
        entity_type="dynamic_pricing_version",
        entity_id=row.id,
        entity_label=row.label,
        summary=f"Retired distance pricing configuration “{row.label}”",
        actor=actor.user,
    )
    await session.commit()
    logger.info("dynamic pricing retired: %s", row.label)
    return _out(row)


# ── preview ─────────────────────────────────────────────────────────────────────────


@router.post(
    "/dynamic-pricing/preview",
    response_model=DynamicPricingPreviewResult,
    summary="Price a road distance with the real engine",
)
async def preview_pricing(
    payload: DynamicPricingPreviewRequest,
    session: SessionDep,
    _: RequireViewer,
) -> DynamicPricingPreviewResult:
    """Run :func:`app.services.pricing.engine.price_by_distance` and return exactly what it said.

    Field overrides are applied to the stored configuration so an admin can try a rate before
    saving it; ``null`` fields are left alone unless they were explicitly sent.
    """
    config = await _resolve_preview_config(session, payload)
    context = PricingContext(
        destination_id=None,
        destination_name="Preview",
        quote_date=datetime.now(UTC).date(),
        currency=config.currency,
        distance_km=payload.distanceKm,
        road_type_id=None,
        road_type_name=None,
        vehicle_id=None,
        vehicle_name=None,
        load_weight_kg=None,
        load_volume_m3=None,
    )
    outcome = engine.price_by_distance(context, config)

    common = {
        "distanceKm": payload.distanceKm,
        "currency": config.currency,
        "configLabel": config.version_label,
        "configId": config.version_id,
    }
    if not outcome.is_priced or outcome.breakdown is None:
        return DynamicPricingPreviewResult(
            priced=False,
            reason=outcome.reason,
            message=outcome.reason_detail,
            **common,
        )

    breakdown = outcome.breakdown
    details = breakdown.pricing_details
    return DynamicPricingPreviewResult(
        priced=True,
        baseRatePerKm=Decimal(details["baseRatePerKm"]) if "baseRatePerKm" in details else None,
        fuelAdjustmentPercent=(
            Decimal(details["fuelAdjustmentPercent"]) if "fuelAdjustmentPercent" in details else None
        ),
        effectiveRatePerKm=(
            Decimal(details["effectiveRatePerKm"]) if "effectiveRatePerKm" in details else None
        ),
        total=breakdown.total,
        adjustments=[
            DynamicPricingPreviewAdjustment(
                label=item.label, amount=item.amount, kind=item.kind.value, detail=item.detail
            )
            for item in breakdown.adjustments
        ],
        notes=list(breakdown.notes),
        **common,
    )


async def _resolve_preview_config(
    session: SessionDep, payload: DynamicPricingPreviewRequest
) -> DynamicPricingConfig:
    base: DynamicPricingConfig | None
    if payload.versionId is not None:
        row = await session.get(DynamicPricingVersion, payload.versionId)
        if row is None:
            raise not_found("Distance pricing configuration", payload.versionId)
        base = to_dynamic_config(row)
    else:
        base = await load_active_dynamic_pricing(session)

    sent = payload.model_fields_set
    if not (sent & {"baseRatePerKm", "fuelAdjustmentPercent", "minCharge"}):
        if base is None:
            raise AppError(
                ErrorCode.VALIDATION,
                "Distance pricing is not configured, so there is nothing to preview. "
                "Enter a base rate to try one first.",
            )
        return base

    if base is None:
        if payload.baseRatePerKm is None:
            raise AppError(
                ErrorCode.VALIDATION,
                "Enter a base rate to preview: no distance pricing configuration is active yet.",
            )
        # Nothing stored to inherit from: the preview is exactly what was typed.
        return DynamicPricingConfig(
            version_id="preview",
            version_label="Unsaved preview",
            base_rate_per_km=payload.baseRatePerKm,
            fuel_adjustment_percent=(
                payload.fuelAdjustmentPercent
                if payload.fuelAdjustmentPercent is not None
                else Decimal("0")
            ),
            min_charge=payload.minCharge if "minCharge" in sent else None,
            currency="KES",
        )

    # Overrides are layered on top of a stored configuration; unsent fields are inherited so a
    # preview never silently changes a rate the admin did not touch. The label says "(preview)"
    # because this exact amount is not what the stored configuration would charge.
    return DynamicPricingConfig(
        version_id=base.version_id,
        version_label=f"{base.version_label} (preview)",
        base_rate_per_km=(
            payload.baseRatePerKm if payload.baseRatePerKm is not None else base.base_rate_per_km
        ),
        fuel_adjustment_percent=(
            payload.fuelAdjustmentPercent
            if payload.fuelAdjustmentPercent is not None
            else base.fuel_adjustment_percent
        ),
        min_charge=payload.minCharge if "minCharge" in sent else base.min_charge,
        currency=base.currency,
    )
