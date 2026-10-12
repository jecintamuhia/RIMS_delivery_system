"""Two gaps closed in the admin surface: an unauthenticated template download, and a password
change that a session cookie alone used to be enough to trigger.

Both are the same class of bug - a request the browser will happily attach credentials to
without the user intending it - so they are tested together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.main import create_app
from app.models import Role, User
from app.security import hash_password

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-long-password-1"
TEMPLATE_PATH = "/api/v1/admin/pricing-import/template"
PASSWORD_PATH = "/api/v1/admin/users/me/password"


@pytest.fixture
def csrf_protection_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Turn the double-submit CSRF check on for the tests that exist to prove it works."""
    monkeypatch.setenv("CSRF_PROTECTION", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


@pytest.fixture
async def anon(engine: Any) -> AsyncIterator[AsyncClient]:
    async with _client() as http:
        yield http


async def _make_user(
    session: AsyncSession, email: str, role: Role, *, password: str = PASSWORD
) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].replace(".", " ").title(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def sign_in(http: AsyncClient, email: str, password: str = PASSWORD) -> Response:
    return await http.post("/api/v1/auth/login", json={"email": email, "password": password})


# ── the pricing template was public ────────────────────────────────────────────────


async def test_an_anonymous_caller_cannot_download_the_pricing_template(
    anon: AsyncClient,
) -> None:
    response = await anon.get(TEMPLATE_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


async def test_a_viewer_can_download_the_pricing_template(
    session: AsyncSession, anon: AsyncClient
) -> None:
    """The template is reference data: the lowest role can read it, and that is all it needs."""
    await _make_user(session, "viewer@rims.test", Role.VIEWER)

    login = await sign_in(anon, "viewer@rims.test")
    assert login.status_code == 200, login.text

    template = await anon.get(TEMPLATE_PATH)

    assert template.status_code == 200, template.text
    assert template.json()["headers"][0] == "destination_name"


# ── a password change was reachable with a session cookie alone ────────────────────


async def test_changing_your_own_password_without_a_csrf_token_is_refused(
    csrf_protection_on: None, session: AsyncSession, anon: AsyncClient
) -> None:
    """A cross-site form post carries the session cookie but cannot set a custom header, so
    the header-only token is what stands between another site and this password."""
    await _make_user(session, "admin@rims.test", Role.ADMIN)
    login = await sign_in(anon, "admin@rims.test")
    assert login.status_code == 200, login.text
    token = login.headers["X-CSRF-Token"]
    payload = {"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD}

    missing = await anon.post(PASSWORD_PATH, json=payload)

    assert missing.status_code == 403
    assert missing.json()["code"] == "FORBIDDEN"
    assert "security token" in missing.json()["message"]

    wrong = await anon.post(PASSWORD_PATH, json=payload, headers={"X-CSRF-Token": "not-the-token"})

    assert wrong.status_code == 403

    accepted = await anon.post(PASSWORD_PATH, json=payload, headers={"X-CSRF-Token": token})

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["email"] == "admin@rims.test"


async def test_the_new_password_is_the_one_that_works_after_the_change(
    csrf_protection_on: None, session: AsyncSession, anon: AsyncClient
) -> None:
    await _make_user(session, "admin@rims.test", Role.ADMIN)
    login = await sign_in(anon, "admin@rims.test")
    changed = await anon.post(
        PASSWORD_PATH,
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    assert changed.status_code == 200, changed.text

    async with _client() as fresh:
        assert (await sign_in(fresh, "admin@rims.test", NEW_PASSWORD)).status_code == 200
        rejected = await sign_in(fresh, "admin@rims.test", PASSWORD)
        assert rejected.status_code in (401, 403)


async def test_reading_the_csrf_token_does_not_require_the_token_itself(
    csrf_protection_on: None, session: AsyncSession, anon: AsyncClient
) -> None:
    """The token has to be readable by the SPA before the SPA can echo it back."""
    await _make_user(session, "admin@rims.test", Role.ADMIN)
    await sign_in(anon, "admin@rims.test")

    me = await anon.post("/api/v1/auth/me")

    assert me.status_code == 200, me.text
    assert me.headers.get("X-CSRF-Token")


async def test_changing_your_own_password_requires_a_signed_in_session(anon: AsyncClient) -> None:
    response = await anon.post(
        PASSWORD_PATH, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"
