"""Provider registry.

The only place that knows which concrete adapter backs a configured provider name. Services
receive the protocols from here, so adding a provider means adding one adapter and one
registry branch - never touching the pricing engine.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import (
    GeocodingProvider,
    GeoLocation,
    LatLng,
    ProviderError,
    RoutingProvider,
    RoutingResult,
)
from app.providers.mapbox import MapboxGeocoder, MapboxRouter
from app.providers.osm import NominatimGeocoder, OsrmRouter

logger = logging.getLogger("app.providers")


class UnavailableGeocoder:
    """Stands in when geocoding is switched off. Always fails; never invents a place.

    Implements ``GeocodingProvider`` so the rest of the system is unaware that geocoding is
    off: callers get a ``ProviderError`` they already know how to turn into a friendly response,
    rather than an ``AttributeError`` or a fabricated result.
    """

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> ProviderError:
        return ProviderError(self.reason, provider=self.name, retryable=False, cause="not_configured")

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[GeoLocation]:
        raise self._fail()

    async def reverse(self, position: LatLng) -> GeoLocation:
        raise self._fail()


class UnavailableRouter:
    """Stands in when routing is switched off. Always fails; never estimates a distance."""

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        raise ProviderError(self.reason, provider=self.name, retryable=False, cause="not_configured")


def build_geocoder(settings: Settings) -> GeocodingProvider:
    name = settings.geocoding_provider
    if name == "osm":
        base = f"{settings.provider_base_url}/geocoding" if settings.provider_base_url else None
        return NominatimGeocoder(base) if base else NominatimGeocoder()
    if name == "mapbox":
        return MapboxGeocoder(settings.provider_key)
    logger.warning("geocoding provider %r is not available; location lookup will fail loudly", name)
    return UnavailableGeocoder(f"geocoding provider '{name}' is not available")


def build_router(settings: Settings) -> RoutingProvider:
    name = settings.routing_provider
    if name == "osm":
        base = f"{settings.provider_base_url}/routing" if settings.provider_base_url else None
        return OsrmRouter(base) if base else OsrmRouter()
    if name == "mapbox":
        return MapboxRouter(settings.provider_key)
    logger.warning("routing provider %r is not available; road distance will fail loudly", name)
    return UnavailableRouter(f"routing provider '{name}' is not available")


@lru_cache(maxsize=1)
def _cached_providers() -> tuple[GeocodingProvider, RoutingProvider]:
    settings = get_settings()
    return build_geocoder(settings), build_router(settings)


def get_providers() -> tuple[GeocodingProvider, RoutingProvider]:
    return _cached_providers()


def reset_providers() -> None:
    """Clear cached providers. Used after settings change and by tests."""
    _cached_providers.cache_clear()
