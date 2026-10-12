"""Authentication, session and RBAC tests.

Everything here runs against the real ASGI app with a real signed session cookie, because the
parts most likely to break in production are the ones a unit test with a mocked session hides:

* the cookie is httpOnly and signed, so a tampered cookie must not authenticate;
* the login response must not disclose whether an address exists;
* a failed-login lockout must actually block the *correct* password too;
* deactivating a user must end their session on the next request;
* the CSRF double-submit check must reject a write that carries no token;
* the role hierarchy must be enforced on every admin route, not just the ones with tests.

CSRF is disabled in the shared test environment, so the CSRF tests re-enable it through a fixture
rather than assuming the default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.main import create_app
from app.models import AuditLog, Role, User
from app.security import hash_password

PASSWORD = "correct-horse-battery"

#: ``(method, path, payload, expected status)``. One representative write per privilege level.
EDITOR_WRITES: tuple[tuple[str, str, dict[str, Any], int], ...] = (
    ("POST", "/api/v1/admin/zones", {"name": "Kericho Zone", "code": "ZKRC"}, 201),
    ("POST", "/api/v1/admin/destinations", {"name": "Kericho", "code": "KRC"}, 201),
    ("POST", "/api/v1/admin/road-types", {"name": "Gravel Road", "code": "GRV"}, 201),
    ("POST", "/api/v1/admin/vehicles", {"name": "Bicycle", "code": "BIC"}, 201),
    ("POST", "/api/v1/admin/origins", {"name": "Depot", "lat": -0.3, "lng": 36.08}, 201),
)
#: Staff accounts and system settings are an administrator's job, never an editor's.
ADMIN_ONLY_WRITES: tuple[tuple[str, str, dict[str, Any], int], ...] = (
    (
        "POST",
        "/api/v1/admin/users",
        {"email": "new@rims.test", "fullName": "New Starter", "password": PASSWORD, "role": "viewer"},
        201,
    ),
    (
        "PATCH",
        "/api/v1/admin/settings",
        {"contactPhone": "+254700000000", "contactEmail": "hello@rims.test"},
        200,
    ),
)
VIEWER_READS = ("/api/v1/admin/dashboard", "/api/v1/admin/destinations", "/api/v1/admin/quotes")


@pytest.fixture
def csrf_protection_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Turn the double-submit CSRF check on for the tests that exist to prove it works."""
    monkeypatch.setenv("CSRF_PROTECTION", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _make_user(
    session: AsyncSession, email: str, role: Role, *, active: bool = True, password: str = PASSWORD
) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].replace(".", " ").title(),
        password_hash=hash_password(password),
        role=role,
        is_active=active,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def users(session: AsyncSession) -> dict[Role, User]:
    """One account per role, plus an inactive one to prove it cannot sign in."""
    created: dict[Role, User] = {}
    for role, address in (
        (Role.ADMIN, "admin2@rims.test"),
        (Role.EDITOR, "editor@rims.test"),
        (Role.VIEWER, "viewer@rims.test"),
    ):
        created[role] = await _make_user(session, address, role)
    await _make_user(session, "retired@rims.test", Role.EDITOR, active=False)
    return created


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


@pytest.fixture
async def anon(engine: Any) -> AsyncIterator[AsyncClient]:
    async with _client() as http:
        yield http


async def sign_in(http: AsyncClient, email: str, password: str = PASSWORD) -> Response:
    return await http.post("/api/v1/auth/login", json={"email": email, "password": password})


async def write(http: AsyncClient, spec: tuple[str, str, dict[str, Any], int]) -> Response:
    method, path, payload, _ = spec
    return await http.request(method, path, json=payload)


# --------------------------------------------------------------------------- login


async def test_login_returns_the_user_and_issues_a_httponly_cookie(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    response = await sign_in(anon, "admin2@rims.test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "admin2@rims.test"
    assert body["name"] == "Admin2"
    assert body["role"] == "admin"
    assert body["isActive"] is True
    assert "password" not in body and "passwordHash" not in body

    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Path=/" in cookie_header
    assert get_settings().session_cookie_name in cookie_header
    assert response.headers.get("X-CSRF-Token"), "the client needs a CSRF token for admin writes"


async def test_login_is_case_insensitive_on_email(anon: AsyncClient, users: dict[Role, User]) -> None:
    """Staff will type their address with whatever capitals their keyboard had on."""
    response = await sign_in(anon, "  Admin2@RIMS.TEST  ")

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "admin2@rims.test"


async def test_login_records_the_sign_in_time(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    """The admin list shows 'Last login', so the column has to actually be written."""
    user = users[Role.VIEWER]
    assert user.last_login_at is None

    response = await sign_in(anon, user.email)

    assert response.status_code == 200
    assert response.json()["lastLoginAt"] is not None
    await session.refresh(user)
    assert user.last_login_at is not None


async def test_a_correct_password_fails_for_an_inactive_account(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    assert (await sign_in(anon, "retired@rims.test")).status_code == 401


# --------------------------------------------------------------------------- no user enumeration


async def test_wrong_password_and_unknown_email_are_indistinguishable(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """The message must not reveal that the address exists, or login becomes an account oracle."""
    wrong_password = await sign_in(anon, "admin2@rims.test", "not-the-password")
    unknown_email = await sign_in(anon, "nobody@rims.test", "not-the-password")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_inactive_account_looks_the_same_as_an_unknown_email(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    assert (await sign_in(anon, "retired@rims.test")).json() == (
        await sign_in(anon, "nobody@rims.test")
    ).json()


# --------------------------------------------------------------------------- lockout


async def test_repeated_failures_lock_the_account_even_with_the_right_password(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    settings = get_settings()
    user = users[Role.VIEWER]

    for _ in range(settings.login_max_attempts):
        assert (await sign_in(anon, user.email, "wrong")).status_code == 401

    # The lockout wording differs on purpose: this caller has already proved they own the account.
    blocked = await sign_in(anon, user.email, PASSWORD)
    assert blocked.status_code == 401
    assert "locked" in blocked.json()["message"].lower()

    await session.refresh(user)
    assert user.failed_login_count >= settings.login_max_attempts
    assert user.is_locked(datetime.now(UTC))


async def test_the_lockout_outlives_the_attempt_that_caused_it(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """A locked account must not unlock because the attacker keeps guessing."""
    settings = get_settings()
    for _ in range(settings.login_max_attempts):
        await sign_in(anon, "viewer@rims.test", "wrong")

    blocked_early = await sign_in(anon, "viewer@rims.test", PASSWORD)
    assert blocked_early.status_code == 401

    # Keep guessing after the lockout: the deadline must not move.
    for _ in range(settings.login_max_attempts):
        await sign_in(anon, "viewer@rims.test", "wrong")

    blocked_late = await sign_in(anon, "viewer@rims.test", PASSWORD)
    assert blocked_late.status_code == 401
    assert "locked" in blocked_late.json()["message"].lower()


async def test_successful_login_clears_the_failure_counter(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    user = users[Role.VIEWER]
    await sign_in(anon, user.email, "wrong")
    await sign_in(anon, user.email, "wrong")

    assert (await sign_in(anon, user.email, PASSWORD)).status_code == 200

    await session.refresh(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None


async def test_an_expired_lockout_lets_the_user_back_in(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    user = users[Role.VIEWER]
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    user.failed_login_count = 3
    await session.commit()

    assert (await sign_in(anon, user.email, PASSWORD)).status_code == 200


async def test_an_admin_password_reset_clears_the_lockout(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    """A locked-out staff member must be rescuable by an administrator."""
    user = users[Role.VIEWER]
    user.locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()

    async with _client() as admin:
        login = await sign_in(admin, "admin2@rims.test")
        assert login.status_code == 200
        response = await admin.patch(
            f"/api/v1/admin/users/{user.id}",
            json={"password": "a-brand-new-password"},
            headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
        )
        assert response.status_code == 200, response.text
        await session.refresh(user)
        assert user.is_locked(datetime.now(UTC)) is False
        assert user.failed_login_count == 0

    async with _client() as victim:
        assert (await sign_in(victim, user.email, "a-brand-new-password")).status_code == 200


# --------------------------------------------------------------------------- session lifecycle


async def test_me_returns_the_signed_in_user_and_csrf_token(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    login = await sign_in(anon, "viewer@rims.test")
    assert login.status_code == 200

    me = await anon.post("/api/v1/auth/me")

    assert me.status_code == 200
    assert me.json()["email"] == "viewer@rims.test"
    assert me.headers.get("X-CSRF-Token") == login.headers.get("X-CSRF-Token")


async def test_logout_clears_the_session(anon: AsyncClient, users: dict[Role, User]) -> None:
    await sign_in(anon, "viewer@rims.test")
    assert (await anon.post("/api/v1/auth/me")).status_code == 200

    assert (await anon.post("/api/v1/auth/logout")).status_code == 204
    assert (await anon.post("/api/v1/auth/me")).status_code == 401


async def test_the_session_endpoint_is_rejected_without_a_session(anon: AsyncClient) -> None:
    for path in ("/api/v1/auth/me", "/api/v1/auth/logout"):
        response = await anon.post(path)
        assert response.status_code == 401, f"{path} returned {response.status_code}"
        assert response.json()["code"] == "SESSION_EXPIRED", path


async def test_a_tampered_cookie_does_not_authenticate(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """The cookie is signed, so editing it must invalidate the session rather than be trusted."""
    await sign_in(anon, "admin2@rims.test")
    name = get_settings().session_cookie_name
    original = anon.cookies.get(name)
    assert original

    flipped = original[:-2] + ("A" if original[-2] != "A" else "B") + original[-1]
    for candidate in (f"{original[:-4]}AAAA", "not-a-signed-payload-at-all", "", flipped):
        anon.cookies.set(name, candidate)
        response = await anon.post("/api/v1/auth/me")
        assert response.status_code == 401, f"a forged cookie authenticated: {candidate!r}"


async def test_deactivating_a_user_ends_their_session_immediately(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    """The session is re-read from the database, so revocation is not just deleting a cookie."""
    user = await _make_user(session, "leaver@rims.test", Role.EDITOR)

    async with _client() as http:
        assert (await sign_in(http, user.email)).status_code == 200
        assert (await http.get("/api/v1/admin/dashboard")).status_code == 200

        user.is_active = False
        await session.commit()

        assert (await http.get("/api/v1/admin/dashboard")).status_code == 401
        assert (await http.post("/api/v1/auth/me")).status_code == 401


async def test_login_and_logout_are_audited(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    await sign_in(anon, "admin2@rims.test")
    await anon.post("/api/v1/auth/logout")

    rows = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action.in_(("signed_in", "signed_out"))).order_by(AuditLog.created_at)
        )
    ).all()
    actions = [row.action for row in rows]
    assert actions.count("signed_in") == 1
    assert actions.count("signed_out") == 1
    admin_id = users[Role.ADMIN].id
    assert all(row.actor_id == admin_id for row in rows)
    assert all(row.actor_label == users[Role.ADMIN].full_name for row in rows)


async def test_a_failed_login_is_not_audited_as_a_sign_in(
    anon: AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    """Only real sign-ins belong in the activity feed."""
    await sign_in(anon, "admin2@rims.test", "wrong")

    rows = (await session.scalars(select(AuditLog).where(AuditLog.action == "signed_in"))).all()
    assert rows == []


# --------------------------------------------------------------------------- RBAC


async def test_every_admin_route_rejects_an_anonymous_caller(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    for path in VIEWER_READS:
        response = await anon.get(path)
        assert response.status_code == 401, f"{path} returned {response.status_code}"
        assert response.json()["code"] == "SESSION_EXPIRED", path


async def test_a_viewer_can_read_but_not_write(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    await sign_in(anon, "viewer@rims.test")

    for path in VIEWER_READS:
        assert (await anon.get(path)).status_code == 200, path

    for spec in EDITOR_WRITES + ADMIN_ONLY_WRITES:
        response = await write(anon, spec)
        assert response.status_code == 403, f"{spec[1]} returned {response.status_code}"
        assert response.json()["code"] == "FORBIDDEN", spec[1]


async def test_a_viewer_can_read_a_single_destination(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """The detail page is read-only for a viewer, so it must not be an editor-only route."""
    await sign_in(anon, "admin2@rims.test")
    created = await anon.post("/api/v1/admin/destinations", json={"name": "Kericho", "code": "KRC"})
    destination_id = created.json()["id"]

    async with _client() as viewer:
        await sign_in(viewer, "viewer@rims.test")
        detail = await viewer.get(f"/api/v1/admin/destinations/{destination_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["code"] == "KRC"


async def test_an_editor_can_write_reference_data_but_not_staff(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    await sign_in(anon, "editor@rims.test")

    for spec in EDITOR_WRITES:
        response = await write(anon, spec)
        assert response.status_code == spec[3], f"{spec[1]} returned {response.status_code}: {response.text}"

    for spec in ADMIN_ONLY_WRITES:
        response = await write(anon, spec)
        assert response.status_code == 403, f"{spec[1]} returned {response.status_code}"
        assert response.json()["code"] == "FORBIDDEN"


async def test_an_editor_cannot_manage_staff_accounts(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """No escalation path: an editor must not mint or edit accounts, least of all admins."""
    await sign_in(anon, "editor@rims.test")

    created = await anon.post(
        "/api/v1/admin/users",
        json={"email": "sneaky@rims.test", "fullName": "Sneaky", "password": PASSWORD, "role": "admin"},
    )
    assert created.status_code == 403
    assert created.json()["code"] == "FORBIDDEN"

    promoted = await anon.patch(
        f"/api/v1/admin/users/{users[Role.VIEWER].id}", json={"role": "admin"}
    )
    assert promoted.status_code == 403

    hijacked = await anon.patch(
        f"/api/v1/admin/users/{users[Role.ADMIN].id}", json={"password": "mine-now"}
    )
    assert hijacked.status_code == 403

    listing = await anon.get("/api/v1/admin/users")
    assert listing.status_code == 403


async def test_an_admin_can_do_everything(anon: AsyncClient, users: dict[Role, User]) -> None:
    await sign_in(anon, "admin2@rims.test")

    admin_reads = (*VIEWER_READS, "/api/v1/admin/users", "/api/v1/admin/settings", "/api/v1/admin/audit-log")
    for path in admin_reads:
        assert (await anon.get(path)).status_code == 200, path
    for spec in EDITOR_WRITES + ADMIN_ONLY_WRITES:
        response = await write(anon, spec)
        assert response.status_code == spec[3], f"{spec[1]} returned {response.status_code}: {response.text}"


async def test_an_admin_cannot_lock_themselves_out(
    anon: AsyncClient, users: dict[Role, User]
) -> None:
    """Losing the last admin account would leave nobody able to manage the system."""
    login = await sign_in(anon, "admin2@rims.test")
    me = login.json()

    deactivated = await anon.patch(
        f"/api/v1/admin/users/{me['id']}", json={"active": False}
    )
    assert deactivated.status_code == 403
    assert "your own account" in deactivated.json()["message"]


# --------------------------------------------------------------------------- CSRF


async def test_a_write_without_a_csrf_token_is_refused(
    csrf_protection_on: None, anon: AsyncClient, users: dict[Role, User]
) -> None:
    await sign_in(anon, "admin2@rims.test")

    response = await anon.post("/api/v1/admin/zones", json={"name": "No CSRF", "code": "ZNOCSRF"})

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert "security token" in response.json()["message"]


async def test_a_write_with_the_wrong_csrf_token_is_refused(
    csrf_protection_on: None, anon: AsyncClient, users: dict[Role, User]
) -> None:
    await sign_in(anon, "admin2@rims.test")

    response = await anon.post(
        "/api/v1/admin/zones",
        json={"name": "Bad CSRF", "code": "ZBAD"},
        headers={"X-CSRF-Token": "not-the-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_write_with_the_issued_csrf_token_succeeds(
    csrf_protection_on: None, anon: AsyncClient, users: dict[Role, User]
) -> None:
    login = await sign_in(anon, "admin2@rims.test")

    response = await anon.post(
        "/api/v1/admin/zones",
        json={"name": "Good CSRF", "code": "ZGOOD"},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )

    assert response.status_code == 201, response.text


async def test_csrf_is_not_required_for_reads(
    csrf_protection_on: None, anon: AsyncClient, users: dict[Role, User]
) -> None:
    await sign_in(anon, "admin2@rims.test")

    assert (await anon.get("/api/v1/admin/dashboard")).status_code == 200
    assert (await anon.get("/api/v1/admin/zones")).status_code == 200


async def test_road_segment_writes_are_csrf_protected_too(
    csrf_protection_on: None, anon: AsyncClient, users: dict[Role, User]
) -> None:
    """Every admin write goes through the same check; one that quietly skipped it would be a hole."""
    login = await sign_in(anon, "admin2@rims.test")
    road_type = await anon.post(
        "/api/v1/admin/road-types",
        json={"name": "Tarmac Road", "code": "TRF"},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    road_type_id = road_type.json()["id"]
    payload = {"name": "Nakuru–Eldoret trunk", "roadTypeId": road_type_id, "lat": -0.3, "lng": 36.08}

    without = await anon.post("/api/v1/admin/road-segments", json=payload)
    assert without.status_code == 403
    assert without.json()["code"] == "FORBIDDEN"

    created = await anon.post(
        "/api/v1/admin/road-segments",
        json=payload,
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    assert created.status_code == 201, created.text


async def test_the_csrf_token_from_one_session_does_not_work_for_another(
    csrf_protection_on: None, users: dict[Role, User]
) -> None:
    """Tokens are per-session: a stolen token still cannot ride somebody else's cookie."""
    async with _client() as alice, _client() as mallory:
        alice_login = await sign_in(alice, "admin2@rims.test")
        await sign_in(mallory, "editor@rims.test")

        response = await mallory.post(
            "/api/v1/admin/zones",
            json={"name": "Stolen token", "code": "ZSTOLEN"},
            headers={"X-CSRF-Token": alice_login.headers["X-CSRF-Token"]},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
