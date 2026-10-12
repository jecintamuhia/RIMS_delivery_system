"""Shared test fixtures.

The suite never touches the network and never writes outside a temporary SQLite database:

* ``DATABASE_URL`` points at an in-memory SQLite shared via ``StaticPool``;
* the geocoding and routing providers are replaced with deterministic stubs, so a test can assert
  on real pipeline behaviour without depending on Nominatim/OSRM being reachable;
* the session secret is set, because sessions are unusable without one and several endpoints
  need to sign in.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-value-not-for-production")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-value-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ.setdefault("DEBUG", "true")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.session import configure_engine
from app.main import create_app
from app.models import DeliveryOrigin, Role, User
from app.providers.base import Confidence, GeoLocation, LatLng, RoutingResult
from app.security import hash_password

NAKURU = GeoLocation(
    id="osm:naakuru",
    label="Nakuru",
    secondary="Nakuru County, Kenya",
    position=LatLng(-0.3031, 36.0800),
    confidence=Confidence.HIGH,
    place_parts=("Nakuru", "Nakuru County", "Kenya"),
)


class StubGeocoder:
    """Deterministic geocoder: knows exactly one place."""

    name = "stub-geocoder"

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[GeoLocation]:
        del country_code
        return [NAKURU] if "nakuru" in query.lower() else []

    async def reverse(self, position: LatLng) -> GeoLocation:
        return NAKURU


class StubRouter:
    """Fixed road distance. The system must use whatever the provider returns - here, 100 km."""

    name = "stub-router"

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        del origin, destination, profile
        return RoutingResult(
            distance_km=100.0,
            duration_seconds=7_200,
            geometry=(LatLng(-0.3031, 36.08), LatLng(-0.5, 36.3)),
            summary="stub route",
            provider=self.name,
        )


@pytest.fixture(scope="session", autouse=True)
def _settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stub_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap both service-level provider lookups for the stubs.

    Patched on the service modules rather than on ``app.providers`` because the services bind the
    name at import time.
    """
    providers = (StubGeocoder(), StubRouter())
    for module in ("app.services.geocoding", "app.services.routing"):
        monkeypatch.setattr(f"{module}.get_providers", lambda: providers)


@pytest.fixture
async def engine() -> AsyncIterator[Any]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    configure_engine(test_engine)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def session(engine: Any) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session


@pytest.fixture
async def admin_user(session: AsyncSession) -> User:
    user = User(
        email="admin@rims.test",
        full_name="Test Admin",
        password_hash=hash_password("correct-horse-battery"),
        role=Role.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def origin(session: AsyncSession) -> DeliveryOrigin:
    """The dispatch point. Seeded explicitly rather than via the lifespan so tests do not depend
    on the app's startup hook running under ``ASGITransport``."""
    row = DeliveryOrigin(
        # The real RIMs dispatch point, not an invented depot: tests that read the dispatch
        # location back should see what production sees.
        name="RIMs Supplies and Hardware — Kenyatta Avenue, Naivasha",
        latitude=-0.7256336,
        longitude=36.4448417,
        is_default=True,
        is_active=True,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
async def client(
    engine: Any, stub_providers: None, admin_user: User, origin: DeliveryOrigin
) -> AsyncIterator[AsyncClient]:
    """An HTTP client against the real app, signed in as an admin."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            "/api/v1/auth/login",
            json={"email": "admin@rims.test", "password": "correct-horse-battery"},
        )
        assert response.status_code == 200, response.text
        http.cookies.update(response.cookies)
        yield http


@pytest.fixture
async def anon_client(engine: Any, stub_providers: None, origin: DeliveryOrigin) -> AsyncIterator[AsyncClient]:
    """An unauthenticated client, for the public endpoints and 401 checks."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
