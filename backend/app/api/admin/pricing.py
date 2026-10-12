"""Pricing versions, rules and activation.

Two invariants are enforced here rather than trusted to convention:

**At most one version is active.** Activating a version retires the previous one in the same
transaction, so a quote can never resolve two competing price lists.

**An active version is immutable.** Editing a rule inside an active version is refused; prices
change by activating a *new* version. Without that, a quote issued last week would silently
acquire a different breakdown when the price was "corrected" today.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.admin_common import audit, ensure_unique, translate_integrity_error
from app.api.admin_schemas import (
    ActivationResult,
    PricingImportReport,
    PricingImportRequest,
    PricingRuleInput,
    PricingRuleModel,
    PricingRuleUpdate,
    PricingVersionInput,
    PricingVersionModel,
    ValidationFinding,
    ValidationRequest,
    VersionValidationResult,
)
from app.api.deps import (
    AdminWriter,
    EditorWriter,
    PaginationDep,
    RequireViewer,
    SessionDep,
    build_page,
)
from app.api.serializers import pricing_rule_model, pricing_version_model
from app.errors import AppError, ErrorCode, not_found
from app.models import (
    AdjustmentType,
    Destination,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    build_scope_key,
)
from app.services.pricing.import_csv import import_pricing_csv, pricing_data_dir
from app.services.pricing.validation import ValidationReport, validate_version

logger = logging.getLogger("app.api.admin.pricing")

router = APIRouter(prefix="/admin", tags=["admin"])


def _version_out(version: PricingVersion, rule_count: int | None = None) -> PricingVersionModel:
    return PricingVersionModel(**pricing_version_model(version, rule_count))


async def _load_version(session: SessionDep, version_id: str) -> PricingVersion:
    version = await session.scalar(
        select(PricingVersion)
        .where(PricingVersion.id == version_id)
        .options(selectinload(PricingVersion.rules))
    )
    if version is None:
        raise not_found("Pricing version", version_id)
    return version


async def _load_rule(session: SessionDep, rule_id: str) -> PricingRule:
    rule = await session.scalar(
        select(PricingRule)
        .where(PricingRule.id == rule_id)
        .options(
            selectinload(PricingRule.version),
            selectinload(PricingRule.destination),
            selectinload(PricingRule.road_type),
            selectinload(PricingRule.vehicle),
        )
    )
    if rule is None:
        raise not_found("Pricing rule", rule_id)
    return rule


def _rule_out(rule: PricingRule) -> PricingRuleModel:
    return PricingRuleModel(**pricing_rule_model(rule, rule.version))


async def _resolve_target_version(session: SessionDep, version_id: str | None) -> PricingVersion:
    """The version a rule should belong to: an explicit one, else the active, else the newest draft."""
    if version_id:
        return await _load_version(session, version_id)
    active = await session.scalar(
        select(PricingVersion).where(PricingVersion.status == PricingVersionStatus.ACTIVE).limit(1)
    )
    if active is not None:
        return active
    draft = await session.scalar(
        select(PricingVersion)
        .where(PricingVersion.status == PricingVersionStatus.DRAFT)
        .order_by(PricingVersion.created_at.desc())
        .limit(1)
    )
    if draft is None:
        raise AppError(
            ErrorCode.VALIDATION,
            "There is no pricing version to add a rule to. Create a pricing version first.",
        )
    return draft


# ── versions ─────────────────────────────────────────────────────────────────────────


@router.get("/pricing-versions", response_model=list[PricingVersionModel], summary="List pricing versions")
async def list_versions(
    session: SessionDep,
    _: RequireViewer,
    status: Annotated[str | None, Query()] = None,
) -> list[PricingVersionModel]:
    stmt = select(PricingVersion).options(selectinload(PricingVersion.rules))
    if status:
        stmt = stmt.where(PricingVersion.status == PricingVersionStatus(status))
    versions = (await session.scalars(stmt.order_by(PricingVersion.effective_from.desc()))).all()
    return [_version_out(version) for version in versions]


@router.post(
    "/pricing-versions/{version_id}/validate",
    response_model=VersionValidationResult,
    summary="Check a pricing version before activating it",
)
async def validate_pricing_version(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
    payload: ValidationRequest | None = None,
) -> VersionValidationResult:
    """Validate a version and, when it passes, record who approved it.

    Read-only apart from the approval stamp. Always returns 200: a version that fails validation
    is a successful *check* with a failing *result*, not a failed request.
    """
    version = await _load_version(session, version_id)
    report = await validate_version(session, version)
    result = _validation_out(report)

    if report.valid and version.status == PricingVersionStatus.DRAFT:
        version.validated_at = datetime.now(UTC)
        version.validated_by_id = actor.user.id
        version.validation_note = payload.note if payload and payload.note else None
        await audit(
            session,
            request,
            action="validated",
            entity_type="pricing_version",
            entity_id=version.id,
            entity_label=version.label,
            summary=f"Validated pricing version “{version.label}”",
            changes={"warnings": len(report.warnings), "note": version.validation_note},
            actor=actor.user,
        )
        await session.commit()
    return result


def _validation_out(report: ValidationReport) -> VersionValidationResult:
    return VersionValidationResult(
        versionId=report.version_id,
        label=report.label,
        status=report.status,
        valid=report.valid,
        ruleCount=report.rule_count,
        destinationCount=report.destination_count,
        findings=[
            ValidationFinding(
                code=item.code,
                severity=item.severity,
                message=item.message,
                destinationName=item.destination_name,
                ruleId=item.rule_id,
            )
            for item in report.findings
        ],
        summary=report.summary,
    )


@router.post(
    "/pricing-versions/{version_id}/confirm-validation",
    response_model=PricingVersionModel,
    summary="Record that a reviewer approved a validated version",
)
async def confirm_validation(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
    payload: ValidationRequest | None = None,
) -> PricingVersionModel:
    """Approve a version an administrator has read. Separate from ``validate`` so that running
    a check - which anyone may do - is not mistaken for approving the prices."""
    version = await _load_version(session, version_id)
    report = await validate_version(session, version)
    if not report.valid:
        raise AppError(
            ErrorCode.VALIDATION,
            f"Pricing version “{version.label}” has {len(report.errors)} problem(s) that must be "
            "fixed before it can be approved.",
            details={
                "versionId": version.id,
                "findings": [
                    {"code": item.code, "message": item.message, "ruleId": item.rule_id}
                    for item in report.errors
                ],
            },
        )
    version.validated_at = datetime.now(UTC)
    version.validated_by_id = actor.user.id
    version.validation_note = payload.note if payload and payload.note else version.validation_note
    await audit(
        session,
        request,
        action="approved",
        entity_type="pricing_version",
        entity_id=version.id,
        entity_label=version.label,
        summary=f"Approved pricing version “{version.label}” for activation",
        changes={"note": version.validation_note, "warnings": len(report.warnings)},
        actor=actor.user,
    )
    await session.commit()
    return _version_out(await _load_version(session, version.id))


@router.post(
    "/pricing-versions",
    response_model=PricingVersionModel,
    status_code=201,
    summary="Create a pricing version",
)
async def create_version(
    payload: PricingVersionInput,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> PricingVersionModel:
    """Versions start as drafts. ``activate`` promotes one in the same request."""
    await ensure_unique(session, "pricing_version", "label", payload.label)
    version = PricingVersion(
        label=payload.label,
        status=PricingVersionStatus.DRAFT,
        effective_from=payload.effectiveFrom,
        effective_to=payload.effectiveTo,
        currency=payload.currency.upper(),
        notes=payload.notes,
        source="manual",
        created_by_id=actor.user.id,
    )
    session.add(version)
    await session.flush()

    await audit(
        session,
        request,
        action="created",
        entity_type="pricing_version",
        entity_id=version.id,
        entity_label=version.label,
        summary=f"Created pricing version “{version.label}”",
        actor=actor.user,
    )
    if payload.activate:
        # Validated here rather than trusted: an imported list can be wrong even if it parsed.
        await _require_valid(session, version)
        version.validated_at = version.validated_at or datetime.now(UTC)
        version.validated_by_id = version.validated_by_id or actor.user.id
        await _activate(session, version, actor=actor.user)
    await session.commit()
    return _version_out(await _load_version(session, version.id))


@router.post(
    "/pricing-versions/{version_id}/activate",
    response_model=ActivationResult,
    summary="Activate a pricing version",
)
async def activate_version(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> ActivationResult:
    """Make this the version new quotes are priced from, retiring the current active one.

    Re-validates on every activation, so prices that were fixed after review cannot slip through,
    and requires a recorded approval: whoever activates is confirming they read the numbers.
    """
    version = await _load_version(session, version_id)
    if version.status != PricingVersionStatus.ACTIVE:
        await _require_valid(session, version)
        if version.validated_at is None:
            raise AppError(
                ErrorCode.VALIDATION,
                f"Pricing version “{version.label}” has not been approved yet. Review it "
                "(POST /pricing-versions/{id}/confirm-validation) before activating.".replace(
                    "{id}", version.id
                ),
                details={"versionId": version.id},
            )
    if version.status == PricingVersionStatus.ACTIVE:
        result = ActivationResult(
            versionId=version.id,
            label=version.label,
            activatedAt=version.activated_at or datetime.now(UTC),
            ruleCount=len(version.rules),
        )
        return result

    result = await _activate(session, version, actor=actor.user)
    await audit(
        session,
        request,
        action="activated",
        entity_type="pricing_version",
        entity_id=version.id,
        entity_label=version.label,
        summary=f"Activated pricing version “{version.label}”",
        changes={"retired": result.retiredLabel},
        actor=actor.user,
    )
    await session.commit()
    logger.info("pricing version %s activated", version.label)
    return result


@router.post(
    "/pricing-versions/{version_id}/retire",
    response_model=PricingVersionModel,
    summary="Retire a pricing version",
)
async def retire_version(
    version_id: str,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> PricingVersionModel:
    """Retiring leaves the rules readable for historical quotes but stops them being used."""
    version = await _load_version(session, version_id)
    if version.status == PricingVersionStatus.DRAFT:
        raise AppError(ErrorCode.VALIDATION, "A draft version cannot be retired; delete is not required.")
    version.status = PricingVersionStatus.RETIRED
    # An approval applies to the version as validated at that moment. Once prices change, whoever
    # activated next is approving the new numbers, not rubber-stamping the old review.
    version.validated_at = None
    version.validated_by_id = None
    version.validation_note = None
    await audit(
        session,
        request,
        action="retired",
        entity_type="pricing_version",
        entity_id=version.id,
        entity_label=version.label,
        summary=f"Retired pricing version “{version.label}”",
        actor=actor.user,
    )
    await session.commit()
    return _version_out(version)


async def _require_valid(session: SessionDep, version: PricingVersion) -> ValidationReport:
    """Raise unless ``version`` is safe to activate. Single source of truth for the gate."""
    report = await validate_version(session, version)
    if not report.valid:
        raise AppError(
            ErrorCode.VALIDATION,
            f"Pricing version “{version.label}” has {len(report.errors)} problem(s) that must be "
            "fixed before it can be activated. Run POST /pricing-versions/{id}/validate for detail."
            .replace("{id}", version.id),
            details={
                "versionId": version.id,
                "findings": [
                    {"code": item.code, "message": item.message, "ruleId": item.rule_id}
                    for item in report.errors
                ],
            },
        )
    return report


async def _activate(
    session: SessionDep, version: PricingVersion, *, actor: object = None
) -> ActivationResult:
    """Move the single ACTIVE marker. Caller commits."""
    now = datetime.now(UTC)
    current = await session.scalar(
        select(PricingVersion).where(PricingVersion.status == PricingVersionStatus.ACTIVE).limit(1)
    )
    retired_id = None
    retired_label = None
    if current is not None and current.id != version.id:
        current.status = PricingVersionStatus.RETIRED
        retired_id = current.id
        retired_label = current.label
        logger.info("retiring pricing version %s", current.label)
    version.status = PricingVersionStatus.ACTIVE
    version.activated_at = now
    await session.flush()
    return ActivationResult(
        versionId=version.id,
        label=version.label,
        activatedAt=now,
        retiredVersionId=retired_id,
        retiredLabel=retired_label,
        ruleCount=len(version.rules),
    )


# ── rules ────────────────────────────────────────────────────────────────────────────


@router.get("/pricing-rules", response_model=dict[str, Any], summary="List pricing rules")
async def list_rules(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    versionId: Annotated[str | None, Query(max_length=32)] = None,
    destinationId: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=160)] = None,
    active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    """The admin rules table. Defaults to the active version when none is specified."""
    conditions = []
    if versionId:
        conditions.append(PricingRule.version_id == versionId)
    else:
        active_version = await session.scalar(
            select(PricingVersion).where(PricingVersion.status == PricingVersionStatus.ACTIVE).limit(1)
        )
        conditions.append(PricingRule.version_id == (active_version.id if active_version else "__none__"))
    if destinationId:
        conditions.append(PricingRule.destination_id == destinationId)
    if active is not None:
        conditions.append(PricingRule.is_active.is_(active))

    base = (
        select(PricingRule)
        .where(*conditions)
        .join(PricingRule.destination)
        .join(PricingRule.version)
        .options(
            selectinload(PricingRule.destination),
            selectinload(PricingRule.road_type),
            selectinload(PricingRule.vehicle),
            selectinload(PricingRule.version),
        )
    )
    if search:
        base = base.where(Destination.name.ilike(f"%{search}%"))

    total = int(
        await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    rules = (
        await session.scalars(
            base.order_by(Destination.name, PricingRule.priority.desc()).offset(page.offset).limit(page.page_size)
        )
    ).all()
    return build_page([_rule_out(rule) for rule in rules], total, page)


@router.get("/pricing-rules/{rule_id}", response_model=PricingRuleModel, summary="Read a pricing rule")
async def get_rule(rule_id: str, session: SessionDep, _: RequireViewer) -> PricingRuleModel:
    return _rule_out(await _load_rule(session, rule_id))


@router.post("/pricing-rules", response_model=PricingRuleModel, status_code=201, summary="Create a pricing rule")
async def create_rule(
    payload: PricingRuleInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> PricingRuleModel:
    version = await _resolve_target_version(session, payload.versionId)
    if version.status == PricingVersionStatus.ACTIVE:
        raise AppError(
            ErrorCode.VALIDATION,
            f"Pricing version “{version.label}” is active and cannot be changed. "
            "Create a new version for this price.",
            details={"versionId": version.id},
        )

    destination = await session.get(Destination, payload.destinationId)
    if destination is None:
        raise AppError(
            ErrorCode.VALIDATION,
            "The destination for this rule does not exist.",
            details={"field": "destinationId"},
        )

    rule = PricingRule(
        version_id=version.id,
        destination_id=destination.id,
        road_type_id=payload.roadTypeId,
        vehicle_id=payload.vehicleId,
        scope_key=build_scope_key(destination.id, payload.roadTypeId, payload.vehicleId),
        label=payload.label,
        base_price=payload.basePrice,
        adjustment_type=AdjustmentType(payload.adjustmentType),
        adjustment_value=payload.adjustmentValue,
        road_adjustment_type=AdjustmentType(payload.roadAdjustmentType),
        road_adjustment_value=payload.roadAdjustmentValue,
        vehicle_adjustment_type=AdjustmentType(payload.vehicleAdjustmentType),
        vehicle_adjustment_value=payload.vehicleAdjustmentValue,
        min_charge=payload.minCharge,
        priority=payload.priority,
        effective_from=payload.effectiveFrom or version.effective_from,
        effective_to=payload.effectiveTo,
        is_active=payload.active,
        notes=payload.notes,
    )
    session.add(rule)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Only a constraint violation becomes a friendly 422. Anything else is a real bug and must
        # keep its own traceback instead of being reported to the user as bad input.
        await session.rollback()
        raise translate_integrity_error(exc) from exc

    await audit(
        session,
        request,
        action="created",
        entity_type="pricing_rule",
        entity_id=rule.id,
        entity_label=f"{destination.name} @ {rule.base_price}",
        summary=(
            f"Set {destination.name} to KES {rule.base_price} in version “{version.label}”"
        ),
        actor=actor.user,
    )
    await session.commit()
    return _rule_out(await _load_rule(session, rule.id))


@router.patch("/pricing-rules/{rule_id}", response_model=PricingRuleModel, summary="Update a pricing rule")
async def update_rule(
    rule_id: str,
    payload: PricingRuleUpdate,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> PricingRuleModel:
    rule = await _load_rule(session, rule_id)
    if rule.version.status == PricingVersionStatus.ACTIVE:
        raise AppError(
            ErrorCode.VALIDATION,
            f"This rule belongs to the active pricing version “{rule.version.label}” and is "
            "immutable. Create a new version to change a price.",
            details={"versionId": rule.version_id},
        )

    before = {"basePrice": str(rule.base_price), "adjustmentType": rule.adjustment_type.value}
    for field in (
        "label",
        "basePrice",
        "adjustmentType",
        "adjustmentValue",
        "roadAdjustmentType",
        "roadAdjustmentValue",
        "vehicleAdjustmentType",
        "vehicleAdjustmentValue",
        "minCharge",
        "priority",
        "effectiveFrom",
        "effectiveTo",
        "active",
        "notes",
    ):
        value = getattr(payload, field)
        if value is None:
            continue
        if field in {"adjustmentType", "roadAdjustmentType", "vehicleAdjustmentType"}:
            setattr(rule, field, AdjustmentType(value))
        else:
            setattr(rule, field, value)

    await audit(
        session,
        request,
        action="updated",
        entity_type="pricing_rule",
        entity_id=rule.id,
        entity_label=f"{rule.destination.name if rule.destination else ''}",
        summary=f"Updated a pricing rule in “{rule.version.label}”",
        changes={
            "fields": {
                "basePrice": {"from": before["basePrice"], "to": str(rule.base_price)},
                "adjustmentType": {
                    "from": before["adjustmentType"],
                    "to": rule.adjustment_type.value,
                },
            }
        },
        actor=actor.user,
    )
    await session.commit()
    return _rule_out(await _load_rule(session, rule.id))


# ── import ────────────────────────────────────────────────────────────────────────────


@router.get("/pricing-import/files", summary="List available server-side price lists")
async def pricing_files(_: RequireViewer) -> list[str]:
    """Expose only CSV basenames from the dedicated pricing data folder."""
    root = pricing_data_dir()
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".csv")


@router.get("/pricing-import/template", summary="Download the pricing CSV template")
async def pricing_template(_: RequireViewer) -> dict[str, Any]:
    """The header row plus one example row, so RIMs can fill in a list we can actually import."""
    return {
        "filename": "rims-pricing-template.csv",
        "headers": list(_TEMPLATE_HEADERS),
        "exampleRow": list(_TEMPLATE_ROW),
        "notes": [
            "destination_name is required and must be unique; a new destination is created if it does not exist.",
            "destination_code is optional; generated from the name when omitted.",
            "destination_aliases is a semicolon-separated list of alternative spellings.",
            "zone_name / zone_code group destinations; both are created if missing.",
            "base_price is required, in shillings, to the cent.",
            "road_adjustment_type is one of none, fixed, percent; "
            "road_adjustment_value must be present unless the type is none.",
            "vehicle_adjustment_type and vehicle_adjustment_value work the same way as the road adjustments.",
            "effective_from defaults to the pricing version's effective_from when left blank.",
            "min_charge, priority and notes are optional.",
        ],
    }


@router.post("/pricing-import", response_model=PricingImportReport, summary="Import a RIMs price list")
async def import_pricing(
    payload: PricingImportRequest,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> PricingImportReport:
    """Validate a CSV against the current configuration and report what would change.

    Defaults to ``dryRun: true``: nothing is written until an operator has read the report and
    asked for the import to be applied. This is the only way prices enter the system.
    """
    report = await import_pricing_csv(
        session,
        filename=payload.filename,
        label=payload.label,
        effective_from=payload.effectiveFrom,
        effective_to=payload.effectiveTo,
        dry_run=payload.dryRun,
        notes=payload.notes,
        actor_id=actor.user.id,
    )
    if not payload.dryRun:
        await audit(
            session,
            request,
            action="imported",
            entity_type="pricing_version",
            entity_id=report.version_id,
            entity_label=payload.label,
            summary=(
                f"Imported {report.rule_count} prices into “{payload.label}” "
                f"({report.destination_count} destinations)"
            ),
            changes={"problems": report.problems[:20]},
            actor=actor.user,
        )
        await session.commit()
        logger.info("pricing import applied: version=%s rules=%s", payload.label, report.rule_count)
    else:
        logger.info(
            "pricing import dry-run: label=%s rows=%s problems=%s",
            payload.label,
            report.rule_count,
            len(report.problems),
        )
    return PricingImportReport(
        dryRun=report.dry_run,
        label=report.label,
        versionId=report.version_id,
        destinationCount=report.destination_count,
        ruleCount=report.rule_count,
        createdDestinations=report.created_destinations,
        createdAliases=report.created_aliases,
        createdZones=report.created_zones,
        createdRoadTypes=report.created_road_types,
        createdVehicles=report.created_vehicles,
        problems=report.problems,
    )


_TEMPLATE_HEADERS = (
    "destination_name",
    "destination_code",
    "destination_aliases",
    "zone_name",
    "zone_code",
    "base_price",
    "road_adjustment_type",
    "road_adjustment_value",
    "vehicle_adjustment_type",
    "vehicle_adjustment_value",
    "road_type_name",
    "vehicle_name",
    "min_charge",
    "priority",
    "effective_from",
    "effective_to",
    "notes",
)

_TEMPLATE_ROW = (
    "Nakuru",
    "NAK",
    "Nakuru Town;Nakuru municipality",
    "Rift Valley",
    "RIFT",
    "1500.00",
    "fixed",
    "250.00",
    "none",
    "",
    "Tarmac",
    "Pickup",
    "",
    "0",
    "",
    "",
    "",
)

