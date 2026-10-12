"""Routing service tests.

Focus is the cache boundary. A cache is an optimisation, so a stale, truncated or hand-edited
entry must never turn into a failed customer quote: the worst acceptable behaviour is to ask the
provider again. These tests also pin the rule that the provider's road distance is used verbatim -
the service never recomputes, smooths or caps it.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.cache import MemoryCache
from app.providers.base import LatLng, RoutingResult
from app.services.routing import RoutingService, _deserialise, _serialise

ORIGIN = LatLng(-0.3031, 36.0800)
DESTINATION = LatLng(-0.5000, 36.3000)


class PoisonableMemoryCache(MemoryCache):
    """The production cache, plus a way to plant an entry for the corruption tests.

    Subclassing rather than reimplementing means these tests exercise the real TTL and LRU
    behaviour instead of a stand-in that agrees with it only by accident.
    """

    def poison(self, key: str, value: Any) -> None:
        """Overwrite a key with something a cache would never legitimately contain."""
        self._store[key] = (time.monotonic() + 3_600, value)

    def keys(self) -> list[str]:
        return list(self._store)


@pytest.fixture(autouse=True)
def _no_real_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that forgets to pass a cache must not reach for the configured one."""
    monkeypatch.setattr("app.services.routing.get_cache", _missing_cache)


async def _missing_cache() -> Any:
    raise AssertionError("the test must supply its own cache")


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch) -> StubCountingRouter:
    """Replace the registry lookup so no network call is possible."""
    instance = StubCountingRouter()
    monkeypatch.setattr("app.services.routing.get_providers", lambda: (StubGeocoder(), instance))
    return instance


class StubGeocoder:
    name = "stub-geocoder"

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[Any]:
        del query, limit, country_code
        return []

    async def reverse(self, position: LatLng) -> Any:
        del position
        raise AssertionError("routing must not reverse geocode")


class StubCountingRouter:
    """Counts how often the provider was actually consulted."""

    name = "stub-router"

    def __init__(self) -> None:
        self.calls = 0

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        del origin, destination, profile
        self.calls += 1
        return RoutingResult(
            distance_km=87.5,
            duration_seconds=6_600,
            geometry=(LatLng(-0.3031, 36.08), LatLng(-0.5, 36.3)),
            summary="stub route",
            provider=self.name,
        )


async def test_route_uses_provider_distance_verbatim(router: StubCountingRouter) -> None:
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)
    result = await service.route(ORIGIN, DESTINATION)

    assert result.distance_km == 87.5
    assert result.duration_seconds == 6_600
    assert result.provider == "stub-router"
    assert router.calls == 1


async def test_second_identical_lookup_is_served_from_cache(router: StubCountingRouter) -> None:
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)

    first = await service.route(ORIGIN, DESTINATION)
    second = await service.route(ORIGIN, DESTINATION)

    assert router.calls == 1, "the second lookup should not have called the provider"
    assert second.distance_km == first.distance_km
    assert second.duration_seconds == first.duration_seconds
    assert second.geometry == first.geometry
    assert second.summary == first.summary


# Entries with no usable distance/duration. These must be thrown away and re-routed.
UNUSABLE = [
    pytest.param({}, id="empty-object"),
    pytest.param({"distance_km": 12.0}, id="missing-duration"),
    pytest.param({"duration_seconds": 600}, id="missing-distance"),
    pytest.param({"distance_km": "not-a-number", "duration_seconds": 600}, id="unparseable-distance"),
    pytest.param({"distance_km": 12.0, "duration_seconds": None}, id="null-duration"),
    pytest.param({"distance_km": None, "duration_seconds": None}, id="both-null"),
    pytest.param({"distance_km": -5.0, "duration_seconds": 600}, id="negative-distance"),
    pytest.param({"distance_km": True, "duration_seconds": 600}, id="bool-is-not-a-distance"),
    pytest.param({"distance_km": {"km": 12}, "duration_seconds": 600}, id="mapping-distance"),
    pytest.param({"distance_km": [12.0], "duration_seconds": 600}, id="list-distance"),
]

# Entries with good measurements but odd *optional* fields. The measurements are what the quote
# depends on, so these are served from the cache with the optional parts degraded - a customer
# should not lose the cached route because a geometry array was truncated.
TOLERATED = [
    pytest.param(
        {"distance_km": 12.0, "duration_seconds": 600.7, "provider": "stub-router"},
        12.0,
        600,
        id="fractional-duration-truncated",
    ),
    pytest.param(
        {"distance_km": 12.0, "duration_seconds": 600, "geometry": "not-a-list"},
        12.0,
        600,
        id="geometry-not-a-list",
    ),
    pytest.param(
        {"distance_km": 12.0, "duration_seconds": 600, "geometry": [[1.0]]},
        12.0,
        600,
        id="truncated-point",
    ),
    pytest.param(
        {"distance_km": "12.50", "duration_seconds": "600"},
        12.5,
        600,
        id="numeric-strings-accepted",
    ),
]


@pytest.mark.parametrize("corrupt", UNUSABLE)
async def test_unusable_cache_entry_falls_back_to_provider(
    corrupt: dict[str, Any], router: StubCountingRouter
) -> None:
    """A cache entry with no usable measurement degrades to a normal lookup instead of a 500."""
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)

    # Prime the cache, then poison the exact key the service will ask for.
    original = await service.route(ORIGIN, DESTINATION)
    cache.poison(_only_key(cache), corrupt)

    result = await service.route(ORIGIN, DESTINATION)

    assert result.distance_km == original.distance_km
    assert result.provider == "stub-router"
    assert router.calls == 2, "an unusable entry must trigger exactly one re-route"


@pytest.mark.parametrize(("payload", "distance", "duration"), TOLERATED)
async def test_odd_optional_cache_fields_do_not_discard_the_route(
    payload: dict[str, Any], distance: float, duration: int, router: StubCountingRouter
) -> None:
    """Good measurements survive even when the optional geometry or summary is junk."""
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)
    await service.route(ORIGIN, DESTINATION)
    cache.poison(_only_key(cache), payload)
    calls_before = router.calls

    result = await service.route(ORIGIN, DESTINATION)

    assert router.calls == calls_before, "the cached measurement should have been used"
    assert result.distance_km == distance
    assert result.duration_seconds == duration
    assert result.geometry is None


async def test_non_dict_cache_entry_is_ignored(router: StubCountingRouter) -> None:
    """A cache backend returning junk (a string, a list, a bool) must not crash the quote."""
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)
    await service.route(ORIGIN, DESTINATION)
    key = _only_key(cache)

    for junk in ("route payload", 42, [1, 2, 3], True, object()):
        cache.poison(key, junk)
        result = await service.route(ORIGIN, DESTINATION)
        assert result.distance_km == 87.5, f"failed for junk value {junk!r}"


async def test_cache_hit_with_usable_data_needs_no_provider(router: StubCountingRouter) -> None:
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)
    # Route once to learn the key the service derives, then replace what it stored.
    await service.route(ORIGIN, DESTINATION)
    cache.poison(
        _only_key(cache),
        _serialise(
            RoutingResult(
                distance_km=42.0,
                duration_seconds=1_800,
                geometry=(LatLng(-0.1, 36.1),),
                summary="cached",
                provider="stub-router",
            )
        ),
    )
    calls_before = router.calls

    result = await service.route(ORIGIN, DESTINATION)

    assert router.calls == calls_before
    assert result.distance_km == 42.0
    assert result.geometry == (LatLng(-0.1, 36.1),)
    assert result.summary == "cached"


async def test_deserialise_rejects_entries_without_a_usable_measurement() -> None:
    with pytest.raises(ValueError):
        _deserialise({"distance_km": None, "duration_seconds": None})

    result = _deserialise({"distance_km": "10", "duration_seconds": "300"})
    assert result.distance_km == 10.0
    assert result.duration_seconds == 300


async def test_provider_failure_surfaces_as_app_error(router: StubCountingRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider errors become a typed API error, never a fabricated distance."""

    async def _boom(origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        del origin, destination, profile
        from app.providers.base import ProviderError

        raise ProviderError("upstream down", provider="stub-router", retryable=True)

    monkeypatch.setattr(router, "route", _boom)
    cache = PoisonableMemoryCache()
    service = RoutingService(cache=cache)

    from app.errors import AppError, ErrorCode

    with pytest.raises(AppError) as excinfo:
        await service.route(ORIGIN, DESTINATION)

    assert excinfo.value.code is ErrorCode.ROUTING_UNAVAILABLE


def _only_key(cache: PoisonableMemoryCache) -> str:
    """The single key the service wrote. Failing loudly here beats a confusing assert later."""
    keys = cache.keys()
    assert len(keys) == 1, f"expected exactly one cache key, got {keys}"
    return keys[0]
