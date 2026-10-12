"""Authentication.

Session-cookie based, as the frontend expects (``credentials: 'include'``, no token in JS).
Login is rate limited, locked out after repeated failures, and never reveals whether an email
exists. A CSRF token is issued with the session so admin writes can be verified.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import CurrentSession, SessionDep, end_session, start_session
from app.api.schemas import AdminUserModel, LoginRequest
from app.api.serializers import user_model
from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.models import User
from app.observability import log_event
from app.security import hash_password, needs_rehash, verify_password
from app.services.audit import record

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AdminUserModel, summary="Sign in to the admin application")
async def login(payload: LoginRequest, response: Response, request: Request, session: SessionDep) -> AdminUserModel:
    settings = get_settings()
    now = datetime.now(UTC)
    email = payload.email.strip().casefold()

    user = await session.scalar(select(User).where(User.email == email))
    generic_failure = AppError(ErrorCode.INVALID_CREDENTIALS)

    if user is None:
        # Still spend the time of a real verification so timing does not disclose existence.
        verify_password(payload.password, hash_password("timing-equaliser"))
        log_event(logger, logging.INFO, "login failed", reason="unknown_email")
        raise generic_failure

    if user.is_locked(now):
        log_event(logger, logging.WARNING, "login blocked: account locked", user_id=user.id)
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            "This account is temporarily locked after too many failed attempts. Try again later.",
        )

    if not user.is_active:
        log_event(logger, logging.INFO, "login failed", reason="inactive")
        raise generic_failure

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            log_event(logger, logging.WARNING, "account locked after failed logins", user_id=user.id)
        await session.commit()
        log_event(logger, logging.INFO, "login failed", reason="bad_password", user_id=user.id)
        raise generic_failure

    if needs_rehash(user.password_hash):
        # Upgrade the stored hash silently after a successful sign-in.
        user.password_hash = hash_password(payload.password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    csrf_token = await start_session(response, user)
    response.headers["X-CSRF-Token"] = csrf_token
    await record(
        session,
        action="signed_in",
        entity_type="user",
        entity_id=user.id,
        entity_label=user.email,
        summary=f"{user.full_name} signed in",
        actor=user,
        request=request,
    )
    await session.commit()
    log_event(logger, logging.INFO, "login succeeded", user_id=user.id, role=user.role.value)
    return user_model(user)


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(response: Response, request: Request, current: CurrentSession, session: SessionDep) -> None:
    await record(
        session,
        action="signed_out",
        entity_type="user",
        entity_id=current.user.id,
        entity_label=current.user.email,
        summary=f"{current.user.full_name} signed out",
        actor=current.user,
        request=request,
    )
    await session.commit()
    await end_session(response)


@router.post("/me", response_model=AdminUserModel, summary="Current signed-in user and CSRF token")
async def me(request: Request, response: Response, current: CurrentSession) -> AdminUserModel:
    """The frontend calls this on load. The CSRF token is returned in a header, not the body."""
    response.headers["X-CSRF-Token"] = current.csrf_token
    del request
    return user_model(current.user)
