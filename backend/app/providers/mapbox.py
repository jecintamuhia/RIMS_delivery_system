"""Mapbox adapters, selected with ``GEOCODING_PROVIDER=mapbox`` / ``ROUTING_PROVIDER=mapbox``.

Present to prove the seam works: nothing in the services or the pricing engine changes when
the provider does. The response parsers are pure functions and are unit-tested against
recorded Mapbox payloads, so they are covered without needing a live token.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.observability import log_event
from app.providers.base import (
    Confidence,
    GeoLocation,
    LatLng,
    ProviderError,
    ProviderNoResult,
    ProviderNotConfigured,
    RoutingResult,
)
from app.providers.http import ProviderHttpClient

logger = logging.getLogger("app.providers.mapbox")

GEOCODING_BASE = "https://api.mapbox.com/geocoding/v5/mapbox.places"
DIRECTIONS_BASE = "https://api.mapbox.com/directions/v5/mapbox"

_CONTEXT_KEYS = ("place", "locality", "district", "region", "country")


class MapboxGeocoder:
    name = "mapbox"

    def __init__(self, token: str | None, base_url: str = GEOCODING_BASE) -> None:
        if not token:
            raise ProviderNotConfigured(self.name, "MAPS_API_KEY")
        self._token = token
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[GeoLocation]:
        params: dict[str, Any] = {
            "access_token": self._token,
            "limit": max(1, min(limit, 10)),
            "language": "en",
        }
        if country_code:
            params["country"] = country_code.lower()
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(f"{self.base_url}/{_quote(query)}.json", params=params)
        return self.parse_search(payload, limit)

    async def reverse(self, position: LatLng) -> GeoLocation:
        params = {"access_token": self._token, "limit": 1, "language": "en"}
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(
                f"{self.base_url}/{position.lng:.6f},{position.lat:.6f}.json", params=params
            )
        results = self.parse_search(payload, 1)
        if not results:
            raise ProviderNoResult("no address found for this point", self.name)
        return results[0]

    def parse_search(self, payload: Any, limit: int) -> list[GeoLocation]:
        if not isinstance(payload, dict):
            raise ProviderError("unexpected geocoding payload", provider=self.name, retryable=False, cause="bad_shape")
        features = payload.get("features")
        if not isinstance(features, list):
            raise ProviderError(
                "geocoding response has no features", provider=self.name, retryable=False, cause="bad_shape"
            )
        results: list[GeoLocation] = []
        for index, feature in enumerate(features):
            if not isinstance(feature, dict):
                continue
            center = feature.get("center")
            if not isinstance(center, (list, tuple)) or len(center) < 2:
                continue
            try:
                position = LatLng(float(center[1]), float(center[0]))
            except (TypeError, ValueError):
                continue
            label = str(feature.get("place_name") or feature.get("text") or "").strip()
            if not label:
                continue
            results.append(
                GeoLocation(
                    id=f"{self.name}:{feature.get('id') or f'{position.lat:.5f},{position.lng:.5f}'}",
                    label=label,
                    secondary=_mapbox_secondary(label, feature),
                    position=position,
                    confidence=Confidence.HIGH if index == 0 else Confidence.MEDIUM,
                    place_parts=_mapbox_parts(feature),
                )
            )
            if len(results) >= limit:
                break
        return results


class MapboxRouter:
    name = "mapbox"

    def __init__(self, token: str | None, base_url: str = DIRECTIONS_BASE) -> None:
        if not token:
            raise ProviderNotConfigured(self.name, "MAPS_API_KEY")
        self._token = token
        self.base_url = base_url.rstrip("/")

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        coords = f"{origin.lng:.6f},{origin.lat:.6f};{destination.lng:.6f},{destination.lat:.6f}"
        params = {
            "access_token": self._token,
            "geometries": "geojson",
            "overview": "full",
            "steps": "false",
        }
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(f"{self.base_url}/{profile}/{coords}", params=params)
        return self.parse_route(payload)

    def parse_route(self, payload: Any) -> RoutingResult:
        if not isinstance(payload, dict):
            raise ProviderError("unexpected route payload", provider=self.name, retryable=False, cause="bad_shape")
        code = payload.get("code")
        if code != "Ok":
            log_event(logger, logging.WARNING, "mapbox could not build a route", code=code)
            raise ProviderError(
                f"mapbox could not build a route: {code}",
                provider=self.name,
                retryable=code not in {"NoRoute", "NoSegment"},
                cause=str(code),
            )
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ProviderError(
                "mapbox returned no routes", provider=self.name, retryable=False, cause="empty_routes"
            )
        best = routes[0]
        try:
            distance_m = float(best["distance"])
            duration_s = float(best["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                "mapbox route is missing distance/duration",
                provider=self.name,
                retryable=False,
                cause="bad_route_shape",
            ) from exc
        if distance_m <= 0:
            raise ProviderError(
                "mapbox returned a non-positive distance",
                provider=self.name,
                retryable=False,
                cause="zero_distance",
            )
        coordinates = (best.get("geometry") or {}).get("coordinates")
        geometry: tuple[LatLng, ...] | None = None
        if isinstance(coordinates, list):
            points = []
            for pair in coordinates:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    try:
                        points.append(LatLng(float(pair[1]), float(pair[0])))
                    except (TypeError, ValueError):
                        continue
            geometry = tuple(points) or None
        return RoutingResult(
            distance_km=round(distance_m / 1000.0, 2),
            duration_seconds=round(duration_s),
            geometry=geometry,
            summary=_mapbox_route_summary(best),
            provider=self.name,
        )


def _mapbox_route_summary(route: dict[str, Any]) -> str | None:
    legs = route.get("legs")
    if not isinstance(legs, list) or not legs:
        return None
    names: list[str] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        steps = leg.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and step.get("name") and step["name"] not in names:
                names.append(str(step["name"]))
    return " via ".join(names[:3]) if names else None


def _mapbox_parts(feature: dict[str, Any]) -> tuple[str, ...]:
    parts: list[str] = []
    context = feature.get("context")
    if isinstance(context, list):
        for item in context:
            if isinstance(item, dict) and any(k in str(item.get("id", "")) for k in _CONTEXT_KEYS):
                text = item.get("text")
                if text:
                    parts.append(str(text))
    text = feature.get("text")
    if text:
        parts.append(str(text))
    return tuple(parts)


def _mapbox_secondary(label: str, feature: dict[str, Any]) -> str | None:
    parts = _mapbox_parts(feature)
    for part in parts:
        if part and part not in label:
            return part
    return None


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def default_mapbox_token() -> str | None:
    settings = get_settings()
    return settings.provider_key
