"""Road distance and duration.

Wraps the configured routing provider with caching and deliberate failure states. A road
distance is only ever the value the provider reports for an actual route - there is no
straight-line fallback, because a fabricated distance would silently change a quote.
"""

from __future__ import annotations

import logging

from app.cache import Cache, get_cache
from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.observability import log_event
from app.providers import get_providers
from app.providers.base import LatLng, ProviderError, RoutingResult
from app.services.geocoding import validate_coordinates

logger = logging.getLogger("app.services.routing")

#: Coordinate rounding used for the cache key. ~1 m: fine for caching, and it stops a client
#: sending marginally different coordinates from missing the cache on every request.
_KEY_PRECISION = 4


class RoutingService:
    def __init__(self, cache: Cache | None = None) -> None:
        self._cache = cache

    async def _resolve_cache(self) -> Cache:
        if self._cache is None:
            self._cache = await get_cache()
        return self._cache

    async def route(self, origin: LatLng, destination: LatLng) -> RoutingResult:
        start = validate_coordinates(origin.lat, origin.lng)
        end = validate_coordinates(destination.lat, destination.lng)

        settings = get_settings()
        cache = await self._resolve_cache()
        cache_key = (
            f"route:{settings.routing_provider}:"
            f"{start.lat:.{_KEY_PRECISION}f},{start.lng:.{_KEY_PRECISION}f}:"
            f"{end.lat:.{_KEY_PRECISION}f},{end.lng:.{_KEY_PRECISION}f}"
        )

        hit = await cache.get(cache_key)
        # A cache backend can hand back anything, so check the shape before trusting the contents.
        if isinstance(hit, dict):
            try:
                return _deserialise(hit)
            except ValueError as exc:
                # A stale or corrupt entry must not fail the quote; fall through and re-route.
                log_event(logger, logging.WARNING, "discarding unusable cached route", reason=str(exc))
        elif hit is not None:
            log_event(logger, logging.WARNING, "discarding cached route of unexpected type")

        _, router = get_providers()
        try:
            result = await router.route(start, end)
        except ProviderError as exc:
            # Logged with provider and reason; coordinates are deliberately not logged.
            log_event(
                logger,
                logging.ERROR,
                "routing failed",
                provider=exc.provider,
                reason=exc.cause or type(exc).__name__,
                retryable=exc.retryable,
            )
            raise AppError(
                ErrorCode.ROUTING_UNAVAILABLE,
                details={"provider": exc.provider} if not settings.is_sqlite else None,
            ) from exc

        await cache.set(cache_key, _serialise(result), settings.cache_ttl_route)
        log_event(
            logger,
            logging.INFO,
            "route calculated",
            provider=result.provider,
            distance_km=result.distance_km,
            duration_seconds=result.duration_seconds,
            cached=False,
        )
        return result


def _serialise(result: RoutingResult) -> dict[str, object]:
    return {
        "distance_km": result.distance_km,
        "duration_seconds": result.duration_seconds,
        "geometry": [[p.lat, p.lng] for p in result.geometry] if result.geometry else None,
        "summary": result.summary,
        "provider": result.provider,
    }


def _deserialise(payload: dict[str, object]) -> RoutingResult:
    """Rebuild a RoutingResult from a cache entry.

    Raises ``ValueError`` for anything malformed. The caller treats that as a cache miss and asks
    the provider, so a corrupt or truncated entry degrades to a normal lookup instead of failing
    the customer's quote.
    """
    raw_geometry = payload.get("geometry")
    geometry: tuple[LatLng, ...] | None = None
    if isinstance(raw_geometry, list):
        points = []
        for pair in raw_geometry:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                try:
                    points.append(LatLng(float(pair[0]), float(pair[1])))
                except (TypeError, ValueError):
                    continue
        geometry = tuple(points) or None

    distance = _as_float(payload.get("distance_km"))
    duration = _as_int(payload.get("duration_seconds"))
    if distance is None or duration is None:
        raise ValueError("cached route is missing a usable distance or duration")
    if distance < 0:
        raise ValueError("cached route has a negative distance")

    summary = payload.get("summary")
    return RoutingResult(
        distance_km=distance,
        duration_seconds=duration,
        geometry=geometry,
        summary=summary if isinstance(summary, str) else None,
        provider=str(payload.get("provider", "unknown")),
    )


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None
