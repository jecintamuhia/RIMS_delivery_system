"""Geometry and place-name helpers.

Kept separate from the ORM and from the services so the matching rules are easy to test and so
distance is never accidentally approximated where a real figure is expected.
"""

from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal
from typing import Any

EARTH_RADIUS_KM = 6371.0088

#: Mapbox/Nominatim administrative suffixes that carry no meaning for matching.
_NOISE_TOKENS = frozenset(
    {
        "county",
        "city",
        "town",
        "village",
        "state",
        "province",
        "region",
        "district",
        "suburb",
        "municipality",
        "kenya",
        "ke",
        "east",
        "west",
        "north",
        "south",
        "central",
        "the",
        "of",
    }
)

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise_place_name(value: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    Used for alias comparison so "Nakuru  Town", "nakuru-town" and "NAKURU TOWN" all match the
    same configured alias. This is name normalisation only - it never invents a destination.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _PUNCTUATION.sub(" ", without_accents)
    return _WHITESPACE.sub(" ", cleaned).strip().casefold()


def place_tokens(value: str) -> set[str]:
    """Significant tokens in a place name, with administrative noise removed."""
    normalised = normalise_place_name(value)
    return {token for token in normalised.split() if token and token not in _NOISE_TOKENS}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance. Used only for configured catchment/segment radii."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def point_in_polygon(lat: float, lng: float, polygon: object) -> bool:
    """Ray-casting point-in-polygon for a GeoJSON Polygon or MultiPolygon.

    Supports polygons with holes: a point inside any outer ring but inside no hole counts as
    inside. Longitude values crossing the antimeridian are not handled; no Kenyan destination
    is affected by that.

    ``polygon`` is typed ``object`` on purpose: it comes straight out of a JSON column, so a
    malformed import can put a list, a string or null where a geometry is expected. Those must
    return False rather than raise - a broken boundary means "cannot confirm", never "in".
    """
    if not isinstance(polygon, dict):
        return False
    geometry_type = polygon.get("type")
    coordinates = polygon.get("coordinates")

    if geometry_type == "Polygon":
        rings = coordinates if isinstance(coordinates, list) else []
        return _in_rings(lat, lng, rings)
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list):
            return False
        return any(
            _in_rings(lat, lng, polygon_rings)
            for polygon_rings in coordinates
            if isinstance(polygon_rings, list)
        )
    return False


def _in_rings(lat: float, lng: float, rings: list[Any]) -> bool:
    if not rings:
        return False
    outer = rings[0]
    if not isinstance(outer, list) or not _ring_contains(lat, lng, outer):
        return False
    return all(not (isinstance(hole, list) and _ring_contains(lat, lng, hole)) for hole in rings[1:])


def _ring_contains(lat: float, lng: float, ring: list[Any]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        i_point, j_point = ring[i], ring[j]
        try:
            i_lng, i_lat = float(i_point[0]), float(i_point[1])
            j_lng, j_lat = float(j_point[0]), float(j_point[1])
        except (TypeError, ValueError, IndexError):
            return False
        if (i_lat > lat) != (j_lat > lat):
            denominator = j_lat - i_lat
            if denominator == 0:
                j = i
                continue
            crossing_lng = i_lng + (lat - i_lat) * (j_lng - i_lng) / denominator
            if lng < crossing_lng:
                inside = not inside
        j = i
    return inside


def is_valid_coordinate(lat: float | Decimal, lng: float | Decimal) -> bool:
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lng_f) or math.isinf(lat_f) or math.isinf(lng_f):
        return False
    return -90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0


def to_decimal_km(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))
