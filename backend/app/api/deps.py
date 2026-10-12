"""FastAPI dependencies: sessions, RBAC, CSRF and pagination.

The session cookie is httpOnly and signed. CSRF uses the double-submit pattern because the
cookie is attached automatically by the browser: without a second, explicitly-sent token, any
origin could drive the admin API with the operator's session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.errors import AppError, ErrorCode, forbidden, not_found
from app.models import Role, User
from app.security import (
    SignatureError,
    csrf_matches,
    generate_session_token,
    new_csrf_token,
    sign_payload,
    unsign_payload,
)

SESSION_USER_KEY = "uid"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


@dataclass(frozen=True, slots=True)
class Session:
    """The authenticated principal for one request."""

    user: User
    csrf_token: str

    @property
    def role(self) -> Role:
        return self.user.role


def settings_dependency() -> Settings:
    return get_settings()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(settings_dependency)]


# ── session lifecycle ─────────────────────────────────────────────────────────────


async def start_session(response: Response, user: User) -> str:
    """Issue a signed session cookie. Returns the CSRF token the client must echo."""
    settings = get_settings()
    csrf_token = new_csrf_token()
    # user id, role and issue/expiry time are signed into the payload so authorisation
    # decisions do not require a database round trip on every call.
    issued = datetime.now(UTC)
    payload = "|".join(
        [
            user.id,
            user.role.value,
            issued.isoformat(),
            (issued + timedelta(seconds=settings.session_max_age_seconds)).isoformat(),
            csrf_token,
        ]
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sign_payload(payload),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_https_only,
        path="/",
    )
    user.last_login_at = issued
    return csrf_token


async def end_session(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.session_cookie_name, path="/")


def read_session(request: Request) -> dict[str, str] | None:
    """Parse and verify the session cookie. Returns None for any invalid/expired cookie."""
    settings = get_settings()
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    try:
        raw_payload = unsign_payload(raw)
    except SignatureError:
        return None
    if raw_payload is None:
        return None
    parts = raw_payload.split("|")
    if len(parts) != 5:
        return None
    user_id, role, issued_raw, expires_raw, csrf_token = parts
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return None
    now = datetime.now(UTC)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return None
    del issued_raw
    return {"user_id": user_id, "role": role, "csrf_token": csrf_token, "expires": expires.isoformat()}


# ── dependencies ───────────────────────────────────────────────────────────────────


async def get_current_session(request: Request, session: SessionDep) -> Session:
    """Require an authenticated session. The user is re-read so deactivation takes effect."""
    raw = read_session(request)
    if raw is None:
        raise AppError(ErrorCode.SESSION_EXPIRED)
    user = await session.scalar(select(User).where(User.id == raw["user_id"]))
    if user is None or not user.is_active:
        raise AppError(ErrorCode.SESSION_EXPIRED)
    return Session(user=user, csrf_token=raw["csrf_token"])


async def get_optional_session(request: Request, session: SessionDep) -> Session | None:
    raw = read_session(request)
    if raw is None:
        return None
    user = await session.scalar(select(User).where(User.id == raw["user_id"]))
    if user is None or not user.is_active:
        return None
    return Session(user=user, csrf_token=raw["csrf_token"])


async def require_csrf(request: Request, current: Session) -> None:
    """Double-submit CSRF check on state-changing admin requests.

    Only the explicit ``X-CSRF-Token`` header counts. The token lives in a readable cookie and
    must be echoed in a header the browser will not attach on its own; accepting it from a
    request body would let a cross-origin form post supply it.
    """
    settings = get_settings()
    if not settings.csrf_protection or request.method in SAFE_METHODS:
        return
    sent = request.headers.get("x-csrf-token")
    if not csrf_matches(sent, current.csrf_token):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Your security token is missing or out of date. Reload the page and try again.",
        )


CurrentSession = Annotated[Session, Depends(get_current_session)]
OptionalSession = Annotated["Session | None", Depends(get_optional_session)]


def require_role(required: Role) -> Any:
    """Dependency factory enforcing a minimum role."""

    async def _dependency(current: CurrentSession) -> Session:
        if not current.role.allows(required):
            raise forbidden(
                f"This action requires the {required.value} role; you are signed in as {current.role.value}."
            )
        return current

    return _dependency


RequireViewer = Annotated[Session, Depends(require_role(Role.VIEWER))]
RequireEditor = Annotated[Session, Depends(require_role(Role.EDITOR))]
RequireAdmin = Annotated[Session, Depends(require_role(Role.ADMIN))]


async def enforce_csrf_admin(request: Request, current: RequireAdmin) -> Session:
    await require_csrf(request, current)
    return current


async def enforce_csrf_editor(request: Request, current: RequireEditor) -> Session:
    await require_csrf(request, current)
    return current


async def enforce_csrf_session(request: Request, current: CurrentSession) -> Session:
    """Any signed-in caller, but only with a valid CSRF token.

    For routes that belong to every authenticated user rather than to a role - changing your
    own password is the one that matters. A session alone must never be enough to act on a
    state-changing request, because the browser attaches the cookie by itself.
    """
    await require_csrf(request, current)
    return current


AdminWriter = Annotated[Session, Depends(enforce_csrf_admin)]
EditorWriter = Annotated[Session, Depends(enforce_csrf_editor)]
SessionWriter = Annotated[Session, Depends(enforce_csrf_session)]


async def read_csrf_token(request: Request, current: CurrentSession) -> dict[str, str]:
    """Endpoint a freshly-signed-in browser uses to obtain the CSRF token it must echo."""
    return {"csrfToken": current.csrf_token}


# ── pagination ─────────────────────────────────────────────────────────────────────

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination(
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


PaginationDep = Annotated[Pagination, Depends(pagination)]


def build_page[T](items: list[T], total: int, page: Pagination) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page.page, "pageSize": page.page_size}


__all__ = [
    "AdminWriter",
    "CurrentSession",
    "EditorWriter",
    "OptionalSession",
    "Pagination",
    "PaginationDep",
    "RequireAdmin",
    "RequireEditor",
    "RequireViewer",
    "Session",
    "SessionDep",
    "SessionWriter",
    "SettingsDep",
    "build_page",
    "end_session",
    "generate_session_token",
    "not_found",
    "read_csrf_token",
    "require_role",
    "start_session",
]
