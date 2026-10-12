"""OpenStreetMap adapters: Nominatim for geocoding, OSRM for road routing.

Chosen as the default because both are keyless, so the system is deployable and testable
without paid provider accounts. Both are rate-limited courtesy APIs - hence the user agent,
the on-disk cache and the low retry count. Set ``GEOCODING_PROVIDER=mapbox`` /
``ROUTING_PROVIDER=mapbox`` with ``MAPS_API_KEY`` to move to a commercial provider.
"""

from __future__ import annotations

import logging
from typing import Any

from app.observability import log_event
from app.providers.base import (
    Confidence,
    GeoLocation,
    LatLng,
    ProviderError,
    ProviderNoResult,
    RoutingResult,
)
from app.providers.http import ProviderHttpClient

logger = logging.getLogger("app.providers.osm")

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OSRM_BASE = "https://router.project-osrm.org"

#: Address elements that help destination matching. Ordered by usefulness.
_PLACE_KEYS = (
    "town",
    "city",
    "village",
    "suburb",
    "county",
    "city_district",
    "district",
    "state",
    "municipality",
)


class NominatimGeocoder:
    """Nominatim search/reverse geocoding."""

    name = "osm-nominatim"

    def __init__(self, base_url: str = NOMINATIM_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[GeoLocation]:
        params: dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": max(1, min(limit, 25)),
            "accept-language": "en",
        }
        if country_code:
            params["countrycodes"] = country_code.lower()
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(f"{self.base_url}/search", params=params)
        if not isinstance(payload, list):
            raise ProviderError("unexpected search payload", provider=self.name, retryable=False, cause="bad_shape")
        results = [self._to_location(item, index) for index, item in enumerate(payload) if isinstance(item, dict)]
        return [r for r in results if r is not None][:limit]

    async def reverse(self, position: LatLng) -> GeoLocation:
        params = {
            "lat": f"{position.lat:.6f}",
            "lon": f"{position.lng:.6f}",
            "format": "jsonv2",
            "addressdetails": 1,
            "accept-language": "en",
        }
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(f"{self.base_url}/reverse", params=params)
        if not isinstance(payload, dict) or payload.get("error"):
            raise ProviderNoResult("no address found for this point", self.name)
        location = self._to_location(payload, 0)
        if location is None:
            raise ProviderNoResult("no address found for this point", self.name)
        # A reverse hit on a building/country scale address is not a precise fix.
        if payload.get("type") in {"administrative", "country"}:
            return GeoLocation(
                id=location.id,
                label=location.label,
                secondary=location.secondary,
                position=location.position,
                confidence=Confidence.LOW,
                place_parts=location.place_parts,
            )
        return location

    def _to_location(self, item: dict[str, Any], index: int) -> GeoLocation | None:
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        label = str(item.get("display_name") or "").strip()
        if not label:
            return None
        # Nominatim omits "address" for some feature types, and it is untyped JSON: narrow once
        # here so everything downstream can treat it as a real mapping.
        raw_address = item.get("address")
        address: dict[str, Any] = raw_address if isinstance(raw_address, dict) else {}
        parts = tuple(
            str(address[key]).strip()
            for key in _PLACE_KEYS
            if address.get(key) and str(address[key]).strip()
        )
        secondary = self._secondary(label, address)
        place_id = item.get("place_id") or item.get("osm_id") or f"{lat:.5f},{lon:.5f}"
        importance = item.get("importance")
        confidence = _confidence_from_importance(importance, index)
        return GeoLocation(
            id=f"{self.name}:{place_id}",
            label=label,
            secondary=secondary,
            position=LatLng(lat, lon),
            confidence=confidence,
            place_parts=parts,
        )

    @staticmethod
    def _secondary(label: str, address: dict[str, Any]) -> str | None:
        """Show the most specific administrative context, not a repeat of the full label."""
        for key in ("suburb", "city_district", "town", "village", "city"):
            value = address.get(key)
            if value and str(value) not in label:
                return str(value)
        return None


def _confidence_from_importance(importance: Any, index: int) -> Confidence:
    """Nominatim ranks results by importance. Rank 0 is essentially always the intended place."""
    if index == 0:
        return Confidence.HIGH
    try:
        score = float(importance)
    except (TypeError, ValueError):
        return Confidence.LOW
    if score >= 0.25:
        return Confidence.MEDIUM
    return Confidence.LOW


class OsrmRouter:
    """OSRM road routing. Distances are the real driven distance, not great-circle."""

    name = "osm-osrm"

    def __init__(self, base_url: str = OSRM_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        coords = f"{origin.lng:.6f},{origin.lat:.6f};{destination.lng:.6f},{destination.lat:.6f}"
        params: dict[str, Any] = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "alternatives": "false",
        }
        url = f"{self.base_url}/route/v1/{profile}/{coords}"
        async with ProviderHttpClient(self.name) as client:
            payload = await client.get_json(url, params=params)
        return self.parse_route(payload)

    def parse_route(self, payload: Any) -> RoutingResult:
        """Pure parser, unit-tested against recorded OSRM payloads."""
        if not isinstance(payload, dict):
            raise ProviderError("unexpected route payload", provider=self.name, retryable=False, cause="bad_shape")
        code = payload.get("code")
        if code != "Ok":
            message = str(payload.get("message") or code or "unknown")
            retryable = code in {"NoRoute", "NoSegment", "InvalidQuery"}
            log_event(logger, logging.WARNING, "router could not build a route", code=code)
            raise ProviderError(
                f"router could not build a route: {message}",
                provider=self.name,
                retryable=retryable,
                cause=str(code),
            )
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ProviderError("router returned no routes", provider=self.name, retryable=False, cause="empty_routes")
        best = routes[0]
        try:
            distance_m = float(best["distance"])
            duration_s = float(best["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                "router route is missing distance/duration",
                provider=self.name,
                retryable=False,
                cause="bad_route_shape",
            ) from exc
        if distance_m <= 0:
            raise ProviderError(
                "router returned a non-positive distance",
                provider=self.name,
                retryable=False,
                cause="zero_distance",
            )
        geometry = _decode_geometry(best.get("geometry"))
        return RoutingResult(
            distance_km=round(distance_m / 1000.0, 2),
            duration_seconds=round(duration_s),
            geometry=geometry,
            summary=_summarise(best),
            provider=self.name,
        )


def _decode_geometry(geometry: Any) -> tuple[LatLng, ...] | None:
    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return None
    points: list[LatLng] = []
    for pair in coordinates:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            try:
                points.append(LatLng(float(pair[1]), float(pair[0])))
            except (TypeError, ValueError):
                continue
    return tuple(points) or None


def _summarise(route: dict[str, Any]) -> str | None:
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
            if not isinstance(step, dict):
                continue
            name = step.get("name") or step.get("ref")
            if name and name not in names:
                names.append(str(name))
    if not names:
        return None
    return " via ".join(names[:3])
