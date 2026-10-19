"""Provider contracts for geocoding and road routing.

This is the seam that keeps the pricing engine provider-agnostic. The pricing engine never
imports ``httpx`` or knows what Nominatim, OSRM or Mapbox are; it is handed a
:class:`RoutingResult`. Swapping providers is a configuration change
(``ROUTING_PROVIDER`` / ``GEOCODING_PROVIDER``), not a code change.

Implementations must be honest: if the provider cannot answer, raise :class:`ProviderError`.
Returning an estimate, a straight-line distance or a cached-looking placeholder would be a lie
the pricing engine cannot detect.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class Confidence(str, enum.Enum):
    """How much to trust a resolved location. Drives the customer confirmation prompt."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class LatLng:
    lat: float
    lng: float

    def rounded(self, places: int = 5) -> LatLng:
        return LatLng(round(self.lat, places), round(self.lng, places))


@dataclass(frozen=True, slots=True)
class GeoLocation:
    """A resolved place. ``id`` is provider-specific and opaque to the rest of the system."""

    id: str
    label: str
    secondary: str | None
    position: LatLng
    confidence: Confidence = Confidence.MEDIUM
    place_parts: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """The actual driving distance between two points, as reported by the provider."""

    distance_km: float
    duration_seconds: int
    geometry: tuple[LatLng, ...] | None
    summary: str | None
    provider: str

    def simplified_geometry(self, max_points: int = 300) -> list[LatLng]:
        """Downsample the polyline for transport to the browser without losing its shape."""
        if not self.geometry:
            return []
        points = list(self.geometry)
        if len(points) <= max_points:
            return points
        step = len(points) / max_points
        sampled = [points[int(i * step)] for i in range(max_points)]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled


class ProviderError(Exception):
    """A provider could not answer. The caller decides the customer-facing failure state."""

    def __init__(self, message: str, *, provider: str, retryable: bool = True, cause: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.cause = cause


class ProviderNotConfigured(ProviderError):
    """Selected provider needs credentials that are absent. Never silently downgraded."""

    def __init__(self, provider: str, missing: str) -> None:
        super().__init__(
            f"provider '{provider}' requires {missing} to be configured",
            provider=provider,
            retryable=False,
        )


class ProviderNoResult(ProviderError):
    """The provider answered but has no match. Not an outage - a genuine 'not found'."""

    def __init__(self, message: str, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=False)


@runtime_checkable
class GeocodingProvider(Protocol):
    name: str

    async def search(self, query: str, *, limit: int = 8, country_code: str | None = None) -> list[GeoLocation]:
        """Resolve free text to candidate places, best match first."""

    async def reverse(self, position: LatLng) -> GeoLocation:
        """Describe a coordinate. Raises :class:`ProviderNoResult` when nothing is near it."""


@runtime_checkable
class RoutingProvider(Protocol):
    name: str

    async def route(self, origin: LatLng, destination: LatLng, *, profile: str = "driving") -> RoutingResult:
        """Actual road distance and duration between two points."""
