"""Location resolution.

Wraps the configured geocoding provider with caching, input validation and deliberate failure
states. The provider supplies geography only; nothing here knows anything about prices.
"""

from __future__ import annotations

import logging
from typing import Any

from app.cache import Cache, get_cache
from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.observability import log_event
from app.providers import get_providers
from app.providers.base import Confidence, GeoLocation, LatLng, ProviderError, ProviderNoResult

logger = logging.getLogger("app.services.geocoding")

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 200


def validate_coordinates(lat: float | None, lng: float | None) -> LatLng:
    settings = get_settings()
    if lat is None or lng is None:
        raise AppError(ErrorCode.INVALID_LOCATION, details={"field": "position"})
    if not (
        settings.service_area_min_lat <= lat <= settings.service_area_max_lat
        and settings.service_area_min_lng <= lng <= settings.service_area_max_lng
    ):
        # A pin outside the configured service area cannot be priced, and pretending otherwise
        # would produce a quote for a delivery RIMs cannot make.
        raise AppError(
            ErrorCode.INVALID_LOCATION,
            details={"reason": "outside_service_area"},
        )
    return LatLng(lat, lng)


class GeocodingService:
    def __init__(self, cache: Cache | None = None) -> None:
        self._cache = cache

    async def _resolve_cache(self) -> Cache:
        if self._cache is None:
            self._cache = await get_cache()
        return self._cache

    async def search(self, query: str, *, limit: int = 8) -> list[GeoLocation]:
        """Free-text place search for the customer-facing autocomplete."""
        cleaned = query.strip()
        if len(cleaned) < MIN_QUERY_LENGTH:
            raise AppError(ErrorCode.INVALID_LOCATION, details={"reason": "query_too_short"})
        if len(cleaned) > MAX_QUERY_LENGTH:
            cleaned = cleaned[:MAX_QUERY_LENGTH]

        settings = get_settings()
        cache = await self._resolve_cache()
        cache_key = f"geocode:search:{settings.geocoding_provider}:{settings.country_code}:{limit}:{cleaned.casefold()}"

        async def _fetch() -> list[dict[str, Any]]:
            provider, _ = get_providers()
            try:
                results = await provider.search(cleaned, limit=limit, country_code=settings.country_code)
            except ProviderNoResult:
                return []
            except ProviderError as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "geocoding search failed",
                    provider=exc.provider,
                    reason=exc.cause or type(exc).__name__,
                )
                raise AppError(
                    ErrorCode.LOCATION_NOT_FOUND,
                    details={"provider": exc.provider},
                ) from exc
            return [_serialise(result) for result in results]

        payload = await _get_or_fetch(cache, cache_key, settings.cache_ttl_geocode, _fetch)
        return [_deserialise(item) for item in payload]

    async def reverse(self, position: LatLng) -> GeoLocation:
        """Describe a pinned coordinate."""
        point = validate_coordinates(position.lat, position.lng)
        settings = get_settings()
        cache = await self._resolve_cache()
        cache_key = f"geocode:reverse:{settings.geocoding_provider}:{point.lat:.5f}:{point.lng:.5f}"

        async def _fetch() -> dict[str, Any]:
            provider, _ = get_providers()
            try:
                result = await provider.reverse(point)
            except ProviderNoResult as exc:
                raise AppError(
                    ErrorCode.LOCATION_NOT_FOUND,
                    details={"provider": exc.provider},
                ) from exc
            except ProviderError as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "reverse geocoding failed",
                    provider=exc.provider,
                    reason=exc.cause or type(exc).__name__,
                )
                raise AppError(
                    ErrorCode.LOCATION_NOT_FOUND,
                    details={"provider": exc.provider},
                ) from exc
            return _serialise(result)

        return _deserialise(await _get_or_fetch(cache, cache_key, settings.cache_ttl_geocode, _fetch))


async def _get_or_fetch(cache: Cache, key: str, ttl: int, factory: Any) -> Any:
    hit = await cache.get(key)
    if hit is not None:
        return hit
    value = await factory()
    if value is not None:
        await cache.set(key, value, ttl)
    return value


def _serialise(location: GeoLocation) -> dict[str, Any]:
    return {
        "id": location.id,
        "label": location.label,
        "secondary": location.secondary,
        "position": {"lat": location.position.lat, "lng": location.position.lng},
        "confidence": location.confidence.value,
        "place_parts": list(location.place_parts),
    }


def _deserialise(payload: dict[str, Any]) -> GeoLocation:
    return GeoLocation(
        id=str(payload.get("id", "")),
        label=str(payload.get("label", "")),
        secondary=payload.get("secondary"),
        position=LatLng(
            float(payload["position"]["lat"]),
            float(payload["position"]["lng"]),
        ),
        confidence=Confidence(payload.get("confidence", "medium")),
        place_parts=tuple(payload.get("place_parts") or ()),
    )


def locations_to_dicts(locations: list[GeoLocation]) -> list[dict[str, Any]]:
    """Shape consumed by the frontend ``GeoLocation`` interface."""
    return [
        {
            "id": location.id,
            "label": location.label,
            **({"secondary": location.secondary} if location.secondary else {}),
            "position": {"lat": location.position.lat, "lng": location.position.lng},
        }
        for location in locations
    ]
