"""Quote orchestration.

The pipeline that connects geography to business pricing:

    resolve location -> route -> resolve destination -> classify road + vehicle
    -> resolve pricing rules -> pricing engine -> immutable breakdown

Two rules govern everything here:

* **Step state is real.** Each step is committed as ``running`` before it executes and
  ``completed`` only after it succeeds, so a polling client observes genuine movement. Nothing
  is marked done that has not been done.
* **A failure is a state, not a number.** When a stage cannot complete the quote is finished
  with a status and a reason code. No stage substitutes an approximate value for a real one.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.models import (
    STEP_ORDER,
    DeliveryOrigin,
    Destination,
    Quote,
    QuoteCalculation,
    QuoteStatus,
    RoadType,
    StepKey,
    StepState,
    SystemSetting,
    VehicleCategory,
)
from app.observability import log_event
from app.providers.base import Confidence, GeoLocation, LatLng
from app.services import destinations as destination_service
from app.services import roads as road_service
from app.services.geocoding import GeocodingService
from app.services.pricing import engine
from app.services.pricing import models as pricing_models
from app.services.pricing.repository import (
    load_active_dynamic_pricing,
    load_active_policy,
    rule_uses_road_types,
    rule_uses_vehicles,
)
from app.services.routing import RoutingService

logger = logging.getLogger("app.services.quotes")

REASON_TO_ERROR_CODE = {
    engine.Reason.DESTINATION_UNSUPPORTED: ErrorCode.DESTINATION_UNSUPPORTED,
    engine.Reason.NO_PRICING_RULE: ErrorCode.NO_PRICING_RULE,
    engine.Reason.ROAD_TYPE_REQUIRED: ErrorCode.ROAD_TYPE_REQUIRED,
    engine.Reason.VEHICLE_REQUIRED: ErrorCode.VEHICLE_REQUIRED,
    engine.Reason.PRICING_NOT_CONFIGURED: ErrorCode.MANUAL_REVIEW,
    engine.Reason.DYNAMIC_PRICING_UNAVAILABLE: ErrorCode.MANUAL_REVIEW,
    engine.Reason.DISTANCE_REQUIRED: ErrorCode.MANUAL_REVIEW,
    engine.Reason.INVALID_INPUT: ErrorCode.MANUAL_REVIEW,
}

#: Fixed-price failures that model B (distance-based pricing) is allowed to answer for.
#: Business-rule refusals - a missing road type or vehicle - are deliberately absent: those
#: must stop the quote even when a dynamic rate exists.
DYNAMIC_PRICING_FALLBACK_REASONS = frozenset(
    {
        engine.Reason.DESTINATION_UNSUPPORTED,
        engine.Reason.NO_PRICING_RULE,
        engine.Reason.PRICING_NOT_CONFIGURED,
    }
)

#: Codes that mean "a RIMs person should look at this quote".
REVIEW_CODES = frozenset(
    {
        ErrorCode.DESTINATION_UNSUPPORTED,
        ErrorCode.NO_PRICING_RULE,
        ErrorCode.ROAD_TYPE_REQUIRED,
        ErrorCode.VEHICLE_REQUIRED,
        ErrorCode.MANUAL_REVIEW,
    }
)

DEFAULT_ORIGIN_KEY = "default_origin_id"

#: Columns refreshed after each step commit. Deliberately excludes relationships - see _commit().
_SCALAR_PROGRESS_COLUMNS: tuple[str, ...] = (
    "status",
    "steps",
    "fee_amount",
    "failure_code",
    "failure_message",
    "failure_details",
    "attempt_count",
    "started_at",
    "completed_at",
    "expires_at",
    "destination_id",
    "road_type_id",
    "road_segment_id",
    "vehicle_id",
    "route_distance_km",
    "route_duration_seconds",
    "pricing_model",
    "pricing_version_id",
)


def initial_steps() -> list[dict[str, str]]:
    return [{"key": step.value, "state": StepState.PENDING.value} for step in STEP_ORDER]


def set_step(steps: list[dict[str, str]], key: StepKey, state: StepState) -> list[dict[str, str]]:
    """Return a *new* steps list with one step's state changed.

    A new list is required rather than mutating in place: SQLAlchemy only marks a JSON column
    dirty when the attribute is reassigned, so an in-place edit is never written - and the
    ``refresh`` in ``_commit`` then overwrites it with the stored value, leaving the customer
    watching steps that never move.
    """
    return [
        {**step, "state": state.value} if step["key"] == key.value else step
        for step in steps
    ]


def mark_step(quote: Quote, key: StepKey, state: StepState) -> None:
    """Assign a new steps list, so the change is flushed."""
    quote.steps = set_step(quote.steps, key, state)


def step_state(steps: list[dict[str, str]], key: StepKey) -> str:
    for step in steps:
        if step["key"] == key.value:
            return step["state"]
    return StepState.PENDING.value


class StageFailure(Exception):
    """Internal signal: a pipeline stage could not complete."""

    def __init__(
        self,
        *,
        step: StepKey,
        code: str,
        message: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.step = step
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message or code)


class QuoteProcessor:
    """Runs the pipeline for one quote and records the outcome.

    The processor is created per job: it holds no cross-request state.
    """

    def __init__(
        self,
        geocoding: GeocodingService | None = None,
        routing: RoutingService | None = None,
    ) -> None:
        self._geocoding = geocoding or GeocodingService()
        self._routing = routing or RoutingService()

    async def process(self, session: AsyncSession, quote: Quote) -> Quote:
        settings = get_settings()
        quote.steps = initial_steps()
        quote.status = QuoteStatus.PROCESSING
        quote.failure_code = None
        quote.failure_message = None
        quote.failure_details = None
        quote.fee_amount = None
        quote.started_at = datetime.now(UTC)
        quote.attempt_count += 1
        await _commit(session, quote)

        try:
            location = await self._run_location_step(session, quote)
            await self._run_route_step(session, quote)
            await self._run_destination_step(session, quote, location)
            await self._run_pricing_step(session, quote)
        except StageFailure as failure:
            await self._finish_with_failure(session, quote, failure)
        except AppError as app_error:
            await self._finish_with_failure(
                session,
                quote,
                StageFailure(
                    step=_current_step(quote.steps),
                    code=app_error.code,
                    message=app_error.message,
                    details=dict(app_error.details) if app_error.details else None,
                ),
            )
        except Exception:
            # An unexpected fault must never leave a quote "processing" forever.
            logger.exception("quote %s failed unexpectedly", quote.id)
            await self._finish_with_failure(
                session,
                quote,
                StageFailure(
                    step=_current_step(quote.steps),
                    code=ErrorCode.SERVER,
                    message="Something went wrong while pricing this delivery.",
                ),
            )
        else:
            await self._finish_success(session, quote, settings)
        quote.completed_at = datetime.now(UTC)
        await session.commit()
        return quote

    # ── stages ───────────────────────────────────────────────────────────────────

    async def _run_location_step(self, session: AsyncSession, quote: Quote) -> GeoLocation:
        mark_step(quote, StepKey.LOCATION, StepState.RUNNING)
        await _commit(session, quote)

        position = LatLng(quote.input_latitude, quote.input_longitude)
        if quote.resolved_label:
            # The customer picked a search result, so the provider already resolved it.
            location = GeoLocation(
                id=quote.location_id or "",
                label=quote.resolved_label,
                secondary=quote.resolved_secondary,
                position=position,
                confidence=Confidence(quote.location_confidence or "medium"),
                place_parts=tuple(
                    part
                    for part in dict.fromkeys(
                        [quote.resolved_secondary or "", quote.resolved_label or ""]
                    )
                    if part
                ),
            )
        else:
            # A dropped pin: describe it so the customer can confirm.
            location = await self._geocoding.reverse(position)
            quote.resolved_label = location.label
            quote.resolved_secondary = location.secondary

        # Both paths must record the coordinates actually priced, because the route step reads
        # quote.latitude/longitude rather than the original input.
        quote.latitude = location.position.lat
        quote.longitude = location.position.lng
        quote.location_confidence = location.confidence.value

        if location.confidence is Confidence.LOW:
            log_event(logger, logging.INFO, "location resolved with low confidence", quote_id=quote.id)

        mark_step(quote, StepKey.LOCATION, StepState.COMPLETED)
        await _commit(session, quote)
        return location

    async def _run_route_step(self, session: AsyncSession, quote: Quote) -> None:
        mark_step(quote, StepKey.ROUTE, StepState.RUNNING)
        await _commit(session, quote)

        origin = await resolve_origin(session)
        quote.origin_id = origin.id
        result = await self._routing.route(
            LatLng(origin.latitude, origin.longitude),
            LatLng(
                _require_coordinate(quote.latitude, StepKey.LOCATION),
                _require_coordinate(quote.longitude, StepKey.LOCATION),
            ),
        )
        quote.route_distance_km = Decimal(str(result.distance_km))
        quote.route_duration_seconds = result.duration_seconds
        quote.route_summary = result.summary
        quote.routing_provider = result.provider
        geometry = result.simplified_geometry()
        quote.route_geometry = [[point.lat, point.lng] for point in geometry] if geometry else None
        mark_step(quote, StepKey.ROUTE, StepState.COMPLETED)
        await _commit(session, quote)

    async def _run_destination_step(
        self, session: AsyncSession, quote: Quote, location: GeoLocation
    ) -> None:
        mark_step(quote, StepKey.DESTINATION, StepState.RUNNING)
        await _commit(session, quote)

        lat = _require_coordinate(quote.latitude, StepKey.LOCATION)
        lng = _require_coordinate(quote.longitude, StepKey.LOCATION)

        resolution = await destination_service.resolve_destination(
            session, lat=lat, lng=lng, location=location
        )
        if isinstance(resolution, destination_service.NoMatch):
            if await load_active_dynamic_pricing(session) is None:
                # No dynamic configuration either, so there is honestly nothing to price from.
                raise StageFailure(
                    step=StepKey.DESTINATION,
                    code=ErrorCode.DESTINATION_UNSUPPORTED,
                    message=(
                        "This delivery location is not currently covered by the configured RIMs "
                        "delivery pricing."
                    ),
                    details={"reason": resolution.reason, "detail": resolution.detail},
                )
            # Model B is configured: the location has no official destination price, so the
            # pipeline continues and prices it from its real road distance instead.
            quote.destination_id = None
            quote.destination_match_method = None
            log_event(
                logger,
                logging.INFO,
                "destination outside the configured price list; distance-based pricing applies",
                quote_id=quote.id,
                reason=resolution.reason,
            )
        else:
            quote.destination_id = resolution.destination.id
            quote.destination_match_method = resolution.method

        road = await road_service.classify_road(
            session, lat=lat, lng=lng, destination_id=quote.destination_id
        )
        quote.road_type_id = road.road_type.id if road.road_type else None
        quote.road_segment_id = road.segment.id if road.segment else None

        vehicle = await road_service.resolve_vehicle(
            session, weight_kg=quote.load_weight_kg, volume_m3=quote.load_volume_m3
        )
        quote.vehicle_id = vehicle.vehicle.id if vehicle.vehicle else None

        mark_step(quote, StepKey.DESTINATION, StepState.COMPLETED)
        await _commit(session, quote)

    async def _run_pricing_step(self, session: AsyncSession, quote: Quote) -> None:
        mark_step(quote, StepKey.PRICING, StepState.RUNNING)
        await _commit(session, quote)

        # "Requires a road type / vehicle" is derived from the pricing configuration itself,
        # never assumed.
        requires_road = await rule_uses_road_types(session)
        requires_vehicle = await rule_uses_vehicles(session)
        policy = await load_active_policy(
            session,
            when=quote_date(),
            requires_road_type=requires_road,
            requires_vehicle=requires_vehicle,
        )

        # Relationship attributes are not loaded here (see _commit), so the display names are
        # fetched explicitly rather than triggering an un-awaitable lazy load.
        destination_name, road_type_name, vehicle_name = await _pricing_display_names(
            session,
            destination_id=quote.destination_id,
            road_type_id=quote.road_type_id,
            vehicle_id=quote.vehicle_id,
        )

        context = pricing_models.PricingContext(
            destination_id=quote.destination_id,
            destination_name=destination_name or "Unlisted delivery location",
            quote_date=quote_date(),
            currency=quote.currency,
            distance_km=quote.route_distance_km,
            road_type_id=quote.road_type_id,
            road_type_name=road_type_name,
            vehicle_id=quote.vehicle_id,
            vehicle_name=vehicle_name,
            load_weight_kg=quote.load_weight_kg,
            load_volume_m3=quote.load_volume_m3,
        )

        if quote.destination_id:
            # Model A: the official RIMs price for this destination, if one is configured.
            outcome = engine.price_delivery(context, policy)
        else:
            # Outside the destination list: model A cannot apply, model B may.
            outcome = pricing_models.PriceOutcome(
                kind=pricing_models.PriceOutcomeKind.UNPRICED,
                reason=engine.Reason.DESTINATION_UNSUPPORTED,
                reason_detail=(
                    "The location is outside every configured RIMs destination price list."
                ),
            )

        if not outcome.is_priced and outcome.reason in DYNAMIC_PRICING_FALLBACK_REASONS:
            # Model B: distance x the active configured rate. Never used for a destination
            # that has an official price, and never invented when no configuration is active.
            dynamic_config = await load_active_dynamic_pricing(session)
            if dynamic_config is not None:
                outcome = engine.price_by_distance(context, dynamic_config)

        if not outcome.is_priced or outcome.breakdown is None:
            reason = outcome.reason or engine.Reason.NO_PRICING_RULE
            raise StageFailure(
                step=StepKey.PRICING,
                code=REASON_TO_ERROR_CODE.get(reason, ErrorCode.MANUAL_REVIEW),
                message=outcome.reason_detail,
                details={
                    "reason": reason,
                    **({"detail": outcome.reason_detail} if outcome.reason_detail else {}),
                },
            )

        breakdown = outcome.breakdown
        distance_based = breakdown.pricing_model is pricing_models.PricingModel.DISTANCE_BASED
        quote.fee_amount = breakdown.total
        quote.currency = breakdown.currency
        quote.pricing_model = breakdown.pricing_model.value
        # A dynamic configuration id must never be written into the fixed-version foreign key.
        quote.pricing_version_id = None if distance_based else breakdown.version_id
        session.add(
            QuoteCalculation(
                quote_id=quote.id,
                pricing_model=breakdown.pricing_model.value,
                base_price=breakdown.base_price,
                total_amount=breakdown.total,
                currency=breakdown.currency,
                breakdown=breakdown.as_breakdown_rows(),
                rule_id=breakdown.rule_id,
                rule_label=breakdown.rule_label,
                pricing_version_id=None if distance_based else breakdown.version_id,
                pricing_version_label=None if distance_based else breakdown.version_label,
                dynamic_pricing_version_id=breakdown.version_id if distance_based else None,
                pricing_details=dict(breakdown.pricing_details) or None,
                notes=list(breakdown.notes),
                distance_km=quote.route_distance_km,
            )
        )
        mark_step(quote, StepKey.PRICING, StepState.COMPLETED)
        await _commit(session, quote)

    # ── outcomes ─────────────────────────────────────────────────────────────────

    def accept(self, session: AsyncSession, quote: Quote) -> Quote:
        """Accept a priced quote.

        Acceptance is refused unless the quote actually carries a price: accepting an unpriced
        or expired quote would record an agreement to a number the system never produced.
        """
        settings = get_settings()
        if not quote.is_priced:
            raise AppError(
                ErrorCode.MANUAL_REVIEW,
                "This delivery has not been priced yet, so there is nothing to accept. "
                "Please contact RIMs for a quotation.",
            )
        if quote.is_expired(datetime.now(UTC)):
            raise AppError(
                ErrorCode.MANUAL_REVIEW,
                f"This estimate expired after {settings.quote_expires_after_hours} hours. "
                "Please recalculate it or contact RIMs.",
            )
        if quote.status is QuoteStatus.ACCEPTED:
            return quote
        quote.status = QuoteStatus.ACCEPTED
        quote.accepted_at = datetime.now(UTC)
        log_event(logger, logging.INFO, "quote accepted", quote_id=quote.id)
        return quote

    async def _finish_success(self, session: AsyncSession, quote: Quote, settings: object) -> None:
        del settings, session
        mark_step(quote, StepKey.ESTIMATE, StepState.COMPLETED)
        quote.status = QuoteStatus.COMPLETED
        quote.expires_at = datetime.now(UTC) + timedelta(hours=get_settings().quote_expires_after_hours)
        log_event(
            logger,
            logging.INFO,
            "quote priced",
            quote_id=quote.id,
            destination_id=quote.destination_id,
            distance_km=float(quote.route_distance_km) if quote.route_distance_km is not None else None,
            amount=float(quote.fee_amount) if quote.fee_amount is not None else None,
            pricing_version_id=quote.pricing_version_id,
        )

    async def _finish_with_failure(
        self, session: AsyncSession, quote: Quote, failure: StageFailure
    ) -> None:
        mark_step(quote, failure.step, StepState.FAILED)
        # Stages after the failure never ran, so they must not look finished. Reassigned rather
        # than mutated in place, for the JSON-column reason documented on ``set_step``.
        failed_index = STEP_ORDER.index(failure.step)
        quote.steps = [
            {**step, "state": StepState.PENDING.value} if index > failed_index else step
            for index, step in enumerate(quote.steps)
        ]
        quote.status = QuoteStatus.NEEDS_REVIEW if failure.code in REVIEW_CODES else QuoteStatus.FAILED
        quote.failure_code = failure.code
        quote.failure_message = failure.message
        quote.failure_details = failure.details or None
        quote.fee_amount = None
        log_event(
            logger,
            logging.WARNING,
            "quote not priced",
            quote_id=quote.id,
            step=failure.step.value,
            code=failure.code,
        )


async def _commit(session: AsyncSession, quote: Quote) -> None:
    """Flush step progress and commit, so a concurrent poll observes real movement.

    Only the scalar columns are refreshed. A bare ``session.refresh(quote)`` expires every
    relationship on the instance, and re-reading one of those in an async context raises
    ``MissingGreenlet`` because the implicit IO cannot be awaited outside a greenlet - which is
    exactly what ``_run_pricing_step`` would have done when naming the destination.
    """
    await session.commit()
    await session.refresh(quote, attribute_names=list(_SCALAR_PROGRESS_COLUMNS))


async def _pricing_display_names(
    session: AsyncSession,
    *,
    destination_id: str | None,
    road_type_id: str | None,
    vehicle_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    if destination_id is None:
        return None, None, None
    names: list[str | None] = [await session.scalar(select(Destination.name).where(Destination.id == destination_id))]
    names.append(
        await session.scalar(select(RoadType.name).where(RoadType.id == road_type_id)) if road_type_id else None
    )
    names.append(
        await session.scalar(select(VehicleCategory.name).where(VehicleCategory.id == vehicle_id))
        if vehicle_id
        else None
    )
    return names[0], names[1], names[2]


def _current_step(steps: list[dict[str, str]]) -> StepKey:
    for candidate in STEP_ORDER:
        if step_state(steps, candidate) == StepState.RUNNING.value:
            return candidate
    for candidate in STEP_ORDER:
        if step_state(steps, candidate) == StepState.PENDING.value:
            return candidate
    return STEP_ORDER[-1]


def _require_coordinate(value: float | None, step: StepKey) -> float:
    if value is None:
        raise StageFailure(step=step, code=ErrorCode.INVALID_LOCATION)
    return float(value)


# ── queries ───────────────────────────────────────────────────────────────────────


async def resolve_origin(session: AsyncSession) -> DeliveryOrigin:
    """The dispatch point: the configured default, else the first active origin."""
    configured = await session.scalar(
        select(SystemSetting.value).where(SystemSetting.key == DEFAULT_ORIGIN_KEY)
    )
    if configured:
        origin = await session.scalar(
            select(DeliveryOrigin).where(
                DeliveryOrigin.id == str(configured), DeliveryOrigin.is_active.is_(True)
            )
        )
        if origin is not None:
            return origin
    origin = await session.scalar(
        select(DeliveryOrigin)
        .where(DeliveryOrigin.is_active.is_(True))
        .order_by(DeliveryOrigin.is_default.desc(), DeliveryOrigin.created_at)
        .limit(1)
    )
    if origin is None:
        raise AppError(
            ErrorCode.SERVER,
            "No delivery origin is configured, so deliveries cannot be routed or priced.",
        )
    return origin


async def load_quote(session: AsyncSession, quote_id: str) -> Quote | None:
    return await session.scalar(
        select(Quote)
        .where(Quote.id == quote_id)
        .options(
            selectinload(Quote.destination),
            selectinload(Quote.road_type),
            selectinload(Quote.vehicle),
            selectinload(Quote.origin),
            selectinload(Quote.pricing_version),
            selectinload(Quote.calculations),
        )
    )


def parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def quote_date(now: datetime | None = None) -> date:
    """Pricing date. A seam so tests can pin 'today'."""
    return (now or datetime.now(UTC)).date()
