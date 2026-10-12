"""Staff accounts, the audit log and application settings.

Passwords are write-only: neither the list nor the detail endpoint returns a hash, and a
password change is recorded in the audit log as ``[redacted]``. Deleting the last active admin is
refused, because that would lock everyone out of the pricing configuration permanently.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.api.admin_common import audit, ensure_unique
from app.api.admin_schemas import (
    PasswordResetRequest,
    UserCreateInput,
    UserUpdateInput,
)
from app.api.deps import (
    AdminWriter,
    PaginationDep,
    RequireAdmin,
    RequireViewer,
    SessionDep,
    SessionWriter,
    build_page,
)
from app.api.schemas import AdminUserModel, AppSettingsModel, UpdateSettingsRequest
from app.api.serializers import audit_model, settings_model, user_model
from app.errors import AppError, ErrorCode, forbidden, not_found
from app.models import (
    AuditLog,
    DeliveryOrigin,
    Destination,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    Role,
    User,
)
from app.observability import log_event
from app.security import hash_password, verify_password
from app.services import settings as settings_service
from app.services.pricing.repository import rule_uses_road_types, rule_uses_vehicles

logger = logging.getLogger("app.api.admin.users")

router = APIRouter(prefix="/admin", tags=["admin"])


# ── users ─────────────────────────────────────────────────────────────────────────────


@router.get("/users", response_model=dict[str, Any], summary="List staff accounts")
async def list_users(
    session: SessionDep,
    page: PaginationDep,
    _: RequireAdmin,
    search: Annotated[str | None, Query(max_length=200)] = None,
    role: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
    if role:
        conditions.append(User.role == Role(role))
    total = int(await session.scalar(select(func.count(User.id)).where(*conditions)) or 0)
    users = (
        await session.scalars(
            select(User).where(*conditions).order_by(User.full_name).offset(page.offset).limit(page.page_size)
        )
    ).all()
    return build_page([user_model(user) for user in users], total, page)


@router.post("/users", response_model=AdminUserModel, status_code=201, summary="Create a staff account")
async def create_user(
    payload: UserCreateInput,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> AdminUserModel:
    email = payload.email.strip().casefold()
    await ensure_unique(session, "user", "email", email)
    user = User(
        email=email,
        full_name=payload.fullName.strip(),
        password_hash=hash_password(payload.password),
        role=Role(payload.role),
        is_active=payload.active,
    )
    session.add(user)
    await session.flush()
    await audit(
        session,
        request,
        action="created",
        entity_type="user",
        entity_id=user.id,
        entity_label=user.email,
        summary=f"Created {user.role.value} account for {user.email}",
        actor=actor.user,
    )
    await session.commit()
    return user_model(user)


@router.patch("/users/{user_id}", response_model=AdminUserModel, summary="Update a staff account")
async def update_user(
    user_id: str,
    payload: UserUpdateInput,
    request: Request,
    session: SessionDep,
    current: AdminWriter,
) -> AdminUserModel:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("User", user_id)
    if user.id == current.user.id and payload.active is False:
        raise forbidden("You cannot deactivate your own account.")
    if (
        user.id == current.user.id
        and payload.role is not None
        and Role(payload.role) is not Role.ADMIN
    ):
        raise forbidden("You cannot remove your own admin role.")

    before = {"role": user.role.value, "active": user.is_active}
    if payload.fullName is not None:
        user.full_name = payload.fullName.strip()
    if payload.password:
        user.password_hash = hash_password(payload.password)
        user.failed_login_count = 0
        user.locked_until = None
    if payload.role is not None:
        new_role = Role(payload.role)
        if new_role is not Role.ADMIN and user.role is Role.ADMIN:
            await _ensure_another_admin(session, user.id)
        user.role = new_role
    if payload.active is not None:
        user.is_active = payload.active
        if not payload.active:
            user.locked_until = None

    await audit(
        session,
        request,
        action="updated",
        entity_type="user",
        entity_id=user.id,
        entity_label=user.email,
        summary=f"Updated account {user.email}",
        changes={
            "role": {"from": before["role"], "to": user.role.value},
            "active": {"from": before["active"], "to": user.is_active},
            # The audit writer redacts this; it is named so the change is still recorded.
            "password": "[redacted]" if payload.password else None,
        },
        actor=current.user,
    )
    await session.commit()
    return user_model(user)


@router.post("/users/me/password", response_model=AdminUserModel, summary="Change your own password")
async def change_own_password(
    payload: PasswordResetRequest,
    request: Request,
    session: SessionDep,
    current: SessionWriter,
) -> AdminUserModel:
    if not verify_password(payload.currentPassword, current.user.password_hash):
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            "Your current password is not correct.",
            details={"field": "currentPassword"},
        )
    if payload.currentPassword == payload.newPassword:
        raise AppError(
            ErrorCode.VALIDATION,
            "The new password must be different from the current one.",
            details={"field": "newPassword"},
        )
    current.user.password_hash = hash_password(payload.newPassword)
    await audit(
        session,
        request,
        action="password_changed",
        entity_type="user",
        entity_id=current.user.id,
        entity_label=current.user.email,
        summary="Changed their own password",
        changes={"password": "[redacted]"},
        actor=current.user,
    )
    await session.commit()
    return user_model(current.user)


async def _ensure_another_admin(session: SessionDep, excluding_user_id: str) -> None:
    others = int(
        await session.scalar(
            select(func.count(User.id)).where(
                User.id != excluding_user_id,
                User.role == Role.ADMIN,
                User.is_active.is_(True),
            )
        )
        or 0
    )
    if others == 0:
        raise AppError(
            ErrorCode.VALIDATION,
            "This is the only active admin account. Create another admin before changing this one.",
        )


# ── audit log ─────────────────────────────────────────────────────────────────────────


@router.get("/audit-log", response_model=dict[str, Any], summary="Read the audit log")
async def audit_log(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    entityType: Annotated[str | None, Query(max_length=40)] = None,
    entityId: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    conditions = []
    if entityType:
        conditions.append(AuditLog.entity_type == entityType)
    if entityId:
        conditions.append(AuditLog.entity_id == entityId)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(AuditLog.summary.ilike(pattern), AuditLog.actor_label.ilike(pattern), AuditLog.action.ilike(pattern))
        )
    total = int(await session.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    return build_page([audit_model(row) for row in rows], total, page)


# ── settings ──────────────────────────────────────────────────────────────────────────


@router.get("/settings", response_model=AppSettingsModel, summary="Read application settings")
async def get_settings_view(session: SessionDep, _: RequireViewer) -> AppSettingsModel:
    return await _build_settings(session)


@router.patch("/settings", response_model=AppSettingsModel, summary="Update application settings")
async def update_settings(
    payload: UpdateSettingsRequest,
    request: Request,
    session: SessionDep,
    actor: AdminWriter,
) -> AppSettingsModel:
    """Dispatch point, contacts and defaults. Secrets are never editable here."""
    changed: dict[str, Any] = {}

    if payload.contactPhone is not None:
        changed["contactPhone"] = payload.contactPhone
        await settings_service.set_value(
            session, settings_service.CONTACT_PHONE, payload.contactPhone, user_id=actor.user.id
        )
    if payload.contactEmail is not None:
        changed["contactEmail"] = payload.contactEmail
        await settings_service.set_value(
            session, settings_service.CONTACT_EMAIL, payload.contactEmail, user_id=actor.user.id
        )
    if payload.defaultRoadTypeId is not None:
        changed["defaultRoadTypeId"] = payload.defaultRoadTypeId
        await settings_service.set_value(
            session, settings_service.DEFAULT_ROAD_TYPE_ID, payload.defaultRoadTypeId, user_id=actor.user.id
        )
    if payload.defaultVehicleId is not None:
        changed["defaultVehicleId"] = payload.defaultVehicleId
        await settings_service.set_value(
            session, settings_service.DEFAULT_VEHICLE_ID, payload.defaultVehicleId, user_id=actor.user.id
        )
    if payload.activePricingVersionId is not None:
        version = await session.get(PricingVersion, payload.activePricingVersionId)
        if version is None:
            raise AppError(
                ErrorCode.VALIDATION,
                "That pricing version does not exist.",
                details={"field": "activePricingVersionId"},
            )
        changed["activePricingVersionId"] = version.label
    if payload.defaultOriginId is not None:
        origin = await session.get(DeliveryOrigin, payload.defaultOriginId)
        if origin is None or not origin.is_active:
            raise AppError(
                ErrorCode.VALIDATION,
                "That delivery origin does not exist or is inactive.",
                details={"field": "defaultOriginId"},
            )
        await _pin_dispatch_origin(session, origin, actor=actor.user)
        changed["defaultOriginId"] = origin.name
    if payload.dispatch is not None:
        # Editing the dispatch point means moving the depot: update the origin in place so the id
        # (and therefore anything already pointing at it) stays stable.
        origin = await settings_service.resolve_dispatch_origin(session)
        if origin is None:
            raise AppError(
                ErrorCode.VALIDATION,
                "No delivery origin exists yet. Create one in Admin > Origins first.",
                details={"field": "dispatch"},
            )
        before = {"name": origin.name, "lat": origin.latitude, "lng": origin.longitude}
        origin.name = payload.dispatch.name.strip()
        origin.latitude = payload.dispatch.lat
        origin.longitude = payload.dispatch.lng
        origin.is_active = True
        await session.flush()
        await _pin_dispatch_origin(session, origin, actor=actor.user)
        changed["dispatch"] = {"from": before, "to": payload.dispatch.model_dump()}

    if changed:
        await audit(
            session,
            request,
            action="updated",
            entity_type="settings",
            entity_id="settings",
            entity_label="Application settings",
            summary="Updated application settings",
            changes=changed,
            actor=actor.user,
        )
        await session.commit()
    return await _build_settings(session)


async def _pin_dispatch_origin(session: SessionDep, origin: DeliveryOrigin, *, actor: object) -> None:
    """Make ``origin`` the single dispatch point and record the choice in settings."""
    others = await session.scalars(
        select(DeliveryOrigin).where(DeliveryOrigin.id != origin.id, DeliveryOrigin.is_default.is_(True))
    )
    for other in others:
        other.is_default = False
    origin.is_default = True
    await settings_service.set_value(
        session, settings_service.DEFAULT_ORIGIN_ID, origin.id, user_id=getattr(actor, "id", None)
    )
    await session.flush()
    log_event(
        logger,
        logging.INFO,
        "dispatch origin pinned",
        origin_id=origin.id,
        dispatch_name=origin.name,
    )


async def _build_settings(session: SessionDep) -> AppSettingsModel:
    from sqlalchemy import select as _select

    from app.models import RoadType, VehicleCategory

    values = await settings_service.get_all(session)
    origin = await settings_service.resolve_dispatch_origin(session)
    active_version = await session.scalar(
        _select(PricingVersion).where(PricingVersion.status == PricingVersionStatus.ACTIVE).limit(1)
    )
    default_road_type_id = values.get(settings_service.DEFAULT_ROAD_TYPE_ID)
    default_vehicle_id = values.get(settings_service.DEFAULT_VEHICLE_ID)
    road_type = (
        await session.get(RoadType, str(default_road_type_id)) if default_road_type_id else None
    )
    vehicle = (
        await session.get(VehicleCategory, str(default_vehicle_id)) if default_vehicle_id else None
    )
    destination_count = int(
        await session.scalar(
            _select(func.count(Destination.id)).where(Destination.is_active.is_(True))
        )
        or 0
    )
    active_rule_count = 0
    if active_version is not None:
        active_rule_count = int(
            await session.scalar(
                _select(func.count(PricingRule.id)).where(
                    PricingRule.version_id == active_version.id, PricingRule.is_active.is_(True)
                )
            )
            or 0
        )

    return settings_model(
        origin=origin,
        contact_phone=values.get(settings_service.CONTACT_PHONE),
        contact_email=values.get(settings_service.CONTACT_EMAIL),
        active_version=active_version,
        map_provider="openstreetmap",
        default_road_type=road_type,
        default_vehicle=vehicle,
        requires_road_type=await rule_uses_road_types(session, active_version.id if active_version else None),
        requires_vehicle=await rule_uses_vehicles(session, active_version.id if active_version else None),
        destination_count=destination_count,
        active_rule_count=active_rule_count,
    )

