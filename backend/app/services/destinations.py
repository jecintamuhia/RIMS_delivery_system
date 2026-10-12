"""Destination resolution.

Answers one question: *which configured RIMs destination applies to this coordinate?*

The answer comes from data, in descending order of confidence:

1. ``alias``          - a configured alias matches a town/area the geocoder reported.
2. ``boundary``       - the point falls inside a configured GeoJSON boundary.
3. ``catchment``      - the point falls inside the destination's configured radius.

If none of those match, the destination is **unsupported**. There is deliberately no
"nearest destination" fallback: borrowing a neighbour's price would state something false about
RIMs' price list, and the spec forbids it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Destination, DestinationAlias
from app.observability import log_event
from app.providers.base import GeoLocation
from app.services.geo import haversine_km, normalise_place_name, place_tokens, point_in_polygon

logger = logging.getLogger("app.services.destinations")

MATCH_ALIAS = "alias"
MATCH_BOUNDARY = "boundary"
MATCH_CATCHMENT = "catchment"


@dataclass(frozen=True, slots=True)
class DestinationMatch:
    destination: Destination
    method: str
    #: What matched, for the audit trail and for explaining the result to an admin.
    evidence: str
    distance_km: float | None = None

    @property
    def confidence(self) -> str:
        return {MATCH_ALIAS: "high", MATCH_BOUNDARY: "high", MATCH_CATCHMENT: "medium"}[self.method]


@dataclass(frozen=True, slots=True)
class NoMatch:
    """Resolution failed deliberately. ``reason`` distinguishes the two honest outcomes."""

    reason: str
    detail: str


ResolutionResult = DestinationMatch | NoMatch

#: Why a destination could not be identified.
NOT_CONFIGURED = "no_destinations_configured"
NO_DESTINATION_COVERS_POINT = "no_destination_covers_point"


def candidate_place_names(location: GeoLocation) -> list[str]:
    """Every string the geocoder gave us that could name a destination."""
    names: list[str] = []
    if location.secondary:
        names.append(location.secondary)
    names.extend(location.place_parts)
    for part in location.label.split(","):
        names.append(part)
    return [name.strip() for name in names if name and name.strip()]


async def load_active_destinations(session: AsyncSession) -> list[Destination]:
    """All destinations that may be matched, with aliases eagerly loaded."""
    stmt = (
        select(Destination)
        .where(Destination.is_active.is_(True))
        .options(selectinload(Destination.aliases))
        .order_by(Destination.name)
    )
    return list((await session.scalars(stmt)).all())


async def load_alias_index(session: AsyncSession) -> dict[str, str]:
    """Normalised name -> destination id, across every active destination.

    Explicit aliases are indexed first so they take precedence over the destination's own name;
    the name and code are then added only where nothing claimed the key. Both queries are ordered
    by name so an ambiguous key always resolves to the same destination.
    """
    index: dict[str, str] = {}

    alias_rows = (
        await session.execute(
            select(DestinationAlias.alias, DestinationAlias.destination_id)
            .join(Destination, Destination.id == DestinationAlias.destination_id)
            .where(DestinationAlias.is_active.is_(True), Destination.is_active.is_(True))
            .order_by(Destination.name, DestinationAlias.alias)
        )
    ).all()
    for alias, destination_id in alias_rows:
        key = normalise_place_name(alias)
        if key:
            index.setdefault(key, destination_id)

    name_rows = (
        await session.execute(
            select(Destination.name, Destination.code, Destination.id)
            .where(Destination.is_active.is_(True))
            .order_by(Destination.name)
        )
    ).all()
    for name, code, destination_id in name_rows:
        for value in (name, code):
            key = normalise_place_name(value)
            if key:
                index.setdefault(key, destination_id)

    return index


def match_by_alias(
    location: GeoLocation, aliases: dict[str, str], by_id: dict[str, Destination]
) -> DestinationMatch | None:
    """Exact alias match against any name the provider reported.

    Matching is on normalised *whole* names first, then on significant tokens, so
    "Nakuru" matches the alias "Nakuru" but "Nakuru Extra" does not accidentally match it.
    """
    for name in candidate_place_names(location):
        key = normalise_place_name(name)
        destination_id = aliases.get(key)
        if destination_id and destination_id in by_id:
            return DestinationMatch(by_id[destination_id], MATCH_ALIAS, f"alias '{name}'")

    provider_tokens: set[str] = set()
    for name in candidate_place_names(location):
        provider_tokens |= place_tokens(name)
    if provider_tokens:
        # Only accept a token match when it is unambiguous across all aliases.
        token_hits = {
            alias_key: destination_id
            for alias_key, destination_id in aliases.items()
            if alias_key in provider_tokens and destination_id in by_id
        }
        distinct = set(token_hits.values())
        if len(distinct) == 1 and len(token_hits) >= 1:
            destination_id = distinct.pop()
            matched = next(alias for alias in token_hits if token_hits[alias] == destination_id)
            return DestinationMatch(by_id[destination_id], MATCH_ALIAS, f"alias '{matched}'")
    return None


def match_by_boundary(
    lat: float, lng: float, destinations: list[Destination]
) -> DestinationMatch | None:
    for destination in destinations:
        if destination.boundary and point_in_polygon(lat, lng, destination.boundary):
            return DestinationMatch(destination, MATCH_BOUNDARY, "inside configured boundary")
    return None


def match_by_catchment(
    lat: float, lng: float, destinations: list[Destination]
) -> DestinationMatch | None:
    """Inside a destination's explicitly configured radius.

    When two configured radii overlap the nearer centre wins - both are areas RIMs defined, so
    choosing between them is a tie-break, not a guess about an uncovered location.
    """
    best: DestinationMatch | None = None
    for destination in destinations:
        if destination.latitude is None or destination.longitude is None:
            continue
        radius = destination.catchment_radius_km
        if radius is None:
            continue
        distance = haversine_km(lat, lng, destination.latitude, destination.longitude)
        if distance <= float(radius) and (best is None or distance < (best.distance_km or float("inf"))):
            best = DestinationMatch(
                destination,
                MATCH_CATCHMENT,
                f"within {radius} km catchment",
                distance_km=round(distance, 3),
            )
    return best


async def resolve_destination(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    location: GeoLocation,
    destinations: list[Destination] | None = None,
    aliases: dict[str, str] | None = None,
) -> ResolutionResult:
    """Resolve which configured destination covers a coordinate."""
    candidates = destinations if destinations is not None else await load_active_destinations(session)
    if not candidates:
        return NoMatch(
            NOT_CONFIGURED,
            "No delivery destinations have been configured yet, so delivery pricing cannot be applied.",
        )

    by_id = {destination.id: destination for destination in candidates}
    alias_index = aliases if aliases is not None else await load_alias_index(session)

    match = match_by_alias(location, alias_index, by_id)
    if match is not None:
        log_event(logger, logging.DEBUG, "destination matched by alias", method=match.method)
        return match

    match = match_by_boundary(lat, lng, candidates)
    if match is not None:
        return match

    match = match_by_catchment(lat, lng, candidates)
    if match is not None:
        return match

    return NoMatch(
        NO_DESTINATION_COVERS_POINT,
        "The selected location is outside every configured RIMs delivery destination.",
    )


def destinations_covering(lat: float, lng: float, destinations: list[Destination]) -> list[Destination]:
    """Diagnostic helper for the admin UI: which configured areas contain this point."""
    covered = []
    for destination in destinations:
        if destination.boundary and point_in_polygon(lat, lng, destination.boundary):
            covered.append(destination)
            continue
        if (
            destination.latitude is not None
            and destination.longitude is not None
            and destination.catchment_radius_km is not None
        ):
            distance = haversine_km(lat, lng, destination.latitude, destination.longitude)
            if distance <= float(destination.catchment_radius_km):
                covered.append(destination)
    return covered
