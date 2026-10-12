"""Public, unauthenticated API used by the customer calculator.

Thin by design: validate, delegate to a service, serialise. No pricing logic lives here, and no
internal detail (stack traces, provider internals, rule ids) is returned to a customer.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app.api.deps import SessionDep
from app.api.schemas import (
    CreateQuoteRequest,
    GeoLocationModel,
    PublicConfig,
    QuoteModel,
    RoutePreviewModel,
)
from app.api.serializers import public_config_model, quote_model, route_model
from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.models import Quote, QuoteStatus
from app.observability import log_event
from app.providers.base import LatLng
from app.services import settings as settings_service
from app.services.geocoding import GeocodingService, locations_to_dicts, validate_coordinates
from app.services.quotes import QuoteProcessor, initial_steps, load_quote, resolve_origin
from app.services.routing import RoutingService

logger = logging.getLogger("app.api.public")

router = APIRouter(prefix="/public", tags=["public"])

MAP_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_ATTRIBUTION = "&copy; OpenStreetMap contributors"


@router.get("/config", response_model=PublicConfig, summary="Company, contact and map defaults")
async def public_config(session: SessionDep) -> PublicConfig:
    """Everything the landing page needs before a customer has done anything."""
    origin = await settings_service.resolve_dispatch_origin(session)
    settings = await settings_service.get_all(session)
    company_name = str(settings.get(settings_service.COMPANY_NAME) or "RIMs Hardware & Supplies Co. Ltd.")
    logo_url = settings.get(settings_service.COMPANY_LOGO_URL)
    zoom = int(settings.get(settings_service.MAP_ZOOM) or 10)
    return public_config_model(
        company_name=company_name,
        logo_url=str(logo_url) if logo_url else None,
        contact_phone=settings.get(settings_service.CONTACT_PHONE),
        contact_email=settings.get(settings_service.CONTACT_EMAIL),
        origin=origin,
        map_center_lat=origin.latitude if origin else -0.3031,
        map_center_lng=origin.longitude if origin else 36.08,
        map_zoom=zoom,
        tile_url=str(settings.get(settings_service.MAP_TILE_URL) or MAP_TILE_URL),
        attribution=str(settings.get(settings_service.MAP_ATTRIBUTION) or MAP_ATTRIBUTION),
    )


@router.get(
    "/locations/search",
    response_model=list[GeoLocationModel],
    summary="Search for a delivery location",
)
async def search_locations(
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[dict[str, object]]:
    del session
    service = GeocodingService()
    try:
        results = await service.search(q, limit=limit)
    except AppError as exc:
        # An empty list is the honest answer for "no matches"; a provider outage is an error.
        if exc.code == ErrorCode.LOCATION_NOT_FOUND:
            return []
        raise
    return locations_to_dicts(results)


@router.get(
    "/locations/reverse",
    response_model=GeoLocationModel,
    summary="Describe a pinned coordinate",
)
async def reverse_geocode(
    session: SessionDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> dict[str, object]:
    del session
    point = validate_coordinates(lat, lng)
    location = await GeocodingService().reverse(point)
    return {
        "id": location.id,
        "label": location.label,
        **({"secondary": location.secondary} if location.secondary else {}),
        "position": {"lat": location.position.lat, "lng": location.position.lng},
    }


@router.get(
    "/route",
    response_model=RoutePreviewModel,
    summary="Preview the road distance to a pinned location",
)
async def preview_route(
    session: SessionDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> RoutePreviewModel:
    """Road distance and travel time from RIMs' dispatch point to a point on the map.

    Lets the locate step show "how far is that" while the customer is still choosing, instead
    of after they have asked for a quote. It deliberately returns **no price**: distance alone
    does not decide the price, and quoting one here would bypass the pricing pipeline.

    Bounded twice: the coordinates must fall inside the configured service area, and this path
    has its own tighter rate-limit budget because each new point costs a routing call.
    """
    point = validate_coordinates(lat, lng)
    origin = await resolve_origin(session)
    result = await RoutingService().route(
        LatLng(origin.latitude, origin.longitude), LatLng(point.lat, point.lng)
    )
    geometry = result.simplified_geometry()
    return RoutePreviewModel(
        distanceKm=Decimal(str(result.distance_km)),
        durationMinutes=round(result.duration_seconds / 60),
        route=route_model([[item.lat, item.lng] for item in geometry]),
    )


@router.post("/quotes", response_model=QuoteModel, status_code=202, summary="Create a delivery quote")
async def create_quote(
    session: SessionDep,
    payload: CreateQuoteRequest,
    background: BackgroundTasks,
    response: Response,
    request: Request,
) -> QuoteModel:
    """Accept a delivery location and start pricing it.

    Returns ``202`` with a ``processing`` quote. The pipeline runs afterwards and the client
    polls ``GET /public/quotes/{id}``; step states come from the backend, never simulated.
    """
    settings = get_settings()
    point = validate_coordinates(payload.position.lat, payload.position.lng)

    origin = await resolve_origin(session)
    quote = Quote(
        status=QuoteStatus.PROCESSING,
        steps=initial_steps(),
        input_label=payload.label,
        input_latitude=point.lat,
        input_longitude=point.lng,
        location_id=payload.locationId,
        customer_reference=payload.reference,
        load_weight_kg=payload.loadWeightKg,
        load_volume_m3=payload.loadVolumeM3,
        currency=settings.default_currency,
        origin_id=origin.id,
    )
    if payload.resolved or payload.locationId:
        # The customer chose a place from search results, so the label is already resolved.
        quote.resolved_label = payload.label
        quote.location_confidence = "high"
    session.add(quote)
    await session.commit()
    await session.refresh(quote)

    log_event(
        logger,
        logging.INFO,
        "quote requested",
        quote_id=quote.id,
        has_reference=bool(payload.reference),
    )
    background.add_task(_process_quote, quote.id, request)
    response.headers["Location"] = f"{settings.api_prefix}/public/quotes/{quote.id}"
    return quote_model(quote)


async def _process_quote(quote_id: str, request: Request) -> None:
    """Run the pipeline on its own session, after the response has been sent."""
    from app.db.session import session_scope

    del request
    with_session = session_scope()
    async with with_session as session:
        quote = await load_quote(session, quote_id)
        if quote is None:
            logger.warning("quote %s vanished before processing", quote_id)
            return
        await QuoteProcessor().process(session, quote)


@router.get("/quotes/{quote_id}", response_model=QuoteModel, summary="Read a quote's progress and result")
async def get_quote(session: SessionDep, quote_id: str) -> QuoteModel:
    quote = await load_quote(session, quote_id)
    if quote is None:
        raise AppError(ErrorCode.NOT_FOUND, "We couldn't find that delivery estimate. Please start again.")
    return quote_model(quote)


@router.post("/quotes/{quote_id}/recalculate", response_model=QuoteModel, summary="Re-run pricing")
async def recalculate_quote(
    session: SessionDep,
    quote_id: str,
    background: BackgroundTasks,
    request: Request,
) -> QuoteModel:
    """Re-run the pipeline for the same location, e.g. after RIMs published new prices."""
    settings = get_settings()
    quote = await load_quote(session, quote_id)
    if quote is None:
        raise AppError(ErrorCode.NOT_FOUND, "We couldn't find that delivery estimate. Please start again.")
    if quote.attempt_count >= settings.max_quote_attempts:
        raise AppError(
            ErrorCode.MANUAL_REVIEW,
            "This estimate has been recalculated too many times. Please contact RIMs for a quotation.",
        )
    quote.status = QuoteStatus.PROCESSING
    quote.steps = initial_steps()
    quote.failure_code = None
    quote.failure_message = None
    quote.fee_amount = None
    await session.commit()
    background.add_task(_process_quote, quote.id, request)
    return quote_model(quote)


@router.post("/quotes/{quote_id}/accept", response_model=QuoteModel, summary="Accept a priced quote")
async def accept_quote(session: SessionDep, quote_id: str) -> QuoteModel:
    quote = await load_quote(session, quote_id)
    if quote is None:
        raise AppError(ErrorCode.NOT_FOUND, "We couldn't find that delivery estimate. Please start again.")
    processor = QuoteProcessor()
    processor.accept(session, quote)
    await session.commit()
    log_event(logger, logging.INFO, "quote accepted", quote_id=quote.id)
    return quote_model(quote)
