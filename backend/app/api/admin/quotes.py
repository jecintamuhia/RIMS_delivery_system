"""Quote administration and the dashboard summary.

Staff see quotes the customer cannot: which version priced them, which rule won, what was
resolved, and why a quote has no fee. Amounts are read-only here - a price changes through the
pricing version workflow, never by editing a quote - so a quote always remains the honest record
of what the customer was told and when.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.api.admin_common import audit
from app.api.admin_schemas import QuoteUpdateInput
from app.api.deps import (
    EditorWriter,
    PaginationDep,
    RequireViewer,
    SessionDep,
    build_page,
)
from app.api.schemas import (
    AdminQuoteModel,
    DashboardSummaryModel,
    NeedsReviewModel,
    TopDestinationModel,
)
from app.api.serializers import admin_quote_model, money_required, quote_list_item
from app.config import get_settings
from app.errors import AppError, ErrorCode, not_found
from app.models import Destination, Quote
from app.models import QuoteStatus as QuoteStatusEnum
from app.services.quotes import load_quote

logger = logging.getLogger("app.api.admin.quotes")

router = APIRouter(prefix="/admin", tags=["admin"])


def _listing() -> Select[Quote]:
    """Base quote query with every relationship the response touches already loaded."""
    return select(Quote).options(
        selectinload(Quote.destination),
        selectinload(Quote.origin),
        selectinload(Quote.road_type),
        selectinload(Quote.vehicle),
        selectinload(Quote.calculations),
    )


def _quote_status(raw: str) -> QuoteStatusEnum:
    """Parse a status filter, rejecting unknown values as a client error."""
    try:
        return QuoteStatusEnum(raw)
    except ValueError as exc:
        allowed = ", ".join(sorted(status.value for status in QuoteStatusEnum))
        raise AppError(
            ErrorCode.VALIDATION, f"Unknown status {raw!r}. Expected one of: {allowed}."
        ) from exc


@router.get("/quotes", response_model=dict[str, Any], summary="List quotes")
async def list_quotes(
    session: SessionDep,
    page: PaginationDep,
    _: RequireViewer,
    status: Annotated[str | None, Query()] = None,
    destinationId: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=160)] = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
    needsReview: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    # ColumnElement, not BinaryExpression: the ``or_`` below is not a two-column comparison.
    conditions: list[ColumnElement[bool]] = [Quote.is_archived.is_(False)]
    if status:
        conditions.append(Quote.status == _quote_status(status))
    if destinationId:
        conditions.append(Quote.destination_id == destinationId)
    if needsReview is not None:
        review = QuoteStatusEnum.NEEDS_REVIEW
        conditions.append(Quote.status == review if needsReview else Quote.status != review)
    if from_:
        conditions.append(Quote.created_at >= _parse_day(from_, start=True))
    if to:
        conditions.append(Quote.created_at <= _parse_day(to, start=False))
    if search:
        # Matches what the customer typed, what we resolved, and their own reference, so staff
        # can find a quote from any of the three things they have to hand.
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Quote.input_label.ilike(pattern),
                Quote.resolved_label.ilike(pattern),
                Quote.customer_reference.ilike(pattern),
                Quote.id.ilike(pattern),
            )
        )

    total = int(await session.scalar(select(func.count(Quote.id)).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            _listing().where(*conditions).order_by(Quote.created_at.desc()).offset(page.offset).limit(page.page_size)
        )
    ).all()
    items = [quote_list_item(row) for row in rows]
    return build_page(items, total, page)


@router.get("/quotes/{quote_id}", response_model=AdminQuoteModel, summary="Read a quote")
async def get_quote(quote_id: str, session: SessionDep, _: RequireViewer) -> AdminQuoteModel:
    quote = await load_quote(session, quote_id)
    if quote is None:
        raise not_found("Quote", quote_id)
    return admin_quote_model(quote)


@router.patch("/quotes/{quote_id}", response_model=AdminQuoteModel, summary="Update a quote's review state")
async def update_quote(
    quote_id: str,
    payload: QuoteUpdateInput,
    request: Request,
    session: SessionDep,
    actor: EditorWriter,
) -> AdminQuoteModel:
    """Staff correction of status and archival. Deliberately cannot change the amount."""
    quote = await load_quote(session, quote_id)
    if quote is None:
        raise not_found("Quote", quote_id)

    before_status = quote.status.value
    if payload.status:
        quote.status = QuoteStatusEnum(payload.status)
        if quote.status is not QuoteStatusEnum.COMPLETED:
            # A quote without a fee cannot read as completed, and marking it so would imply a
            # price RIMs never gave.
            quote.fee_amount = None
    if payload.archived is not None:
        quote.is_archived = payload.archived

    await audit(
        session,
        request,
        action="updated",
        entity_type="quote",
        entity_id=quote.id,
        entity_label=quote.customer_reference or quote.resolved_label or quote.id,
        summary=f"Updated quote {quote.id}",
        changes={
            "status": {"from": before_status, "to": quote.status.value},
            "archived": quote.is_archived,
            "reviewNote": payload.reviewNote,
        },
        actor=actor.user,
    )
    await session.commit()
    return admin_quote_model(await load_quote(session, quote_id) or quote)


# ── dashboard ─────────────────────────────────────────────────────────────────────────


@router.get("/dashboard", response_model=DashboardSummaryModel, summary="Dashboard summary")
async def dashboard(session: SessionDep, _: RequireViewer) -> DashboardSummaryModel:
    """Volume, quoted value and what needs a human. Aggregated in SQL, not in Python."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    async def _count_since(session: AsyncSession, column: InstrumentedAttribute[datetime], start: datetime) -> int:
        """How many quotes were created at or after ``start``. Counted in SQL, never in Python."""
        result = await session.execute(select(func.count(Quote.id)).where(column >= start))
        return int(result.scalar_one())

    quotes_today = await _count_since(session, Quote.created_at, today_start)
    quotes_week = await _count_since(session, Quote.created_at, week_start)

    priced_total = await session.execute(
        select(func.coalesce(func.sum(Quote.fee_amount), 0), func.avg(Quote.route_distance_km)).where(
            Quote.status.in_([QuoteStatusEnum.COMPLETED, QuoteStatusEnum.ACCEPTED])
        )
    )
    total_value, average_distance = priced_total.one()
    currency = get_settings().default_currency

    top_rows = (
        await session.execute(
            select(Destination.name, func.count(Quote.id))
            .join(Quote, Quote.destination_id == Destination.id)
            .group_by(Destination.name)
            .order_by(func.count(Quote.id).desc())
            .limit(5)
        )
    ).all()

    review_rows = (
        await session.scalars(
            select(Quote)
            .where(Quote.status == QuoteStatusEnum.NEEDS_REVIEW, Quote.is_archived.is_(False))
            .order_by(Quote.created_at.desc())
            .limit(5)
        )
    ).all()

    status_counts = dict(
        (
            await session.execute(
                select(Quote.status, func.count(Quote.id)).group_by(Quote.status)
            )
        ).all()
    )

    return DashboardSummaryModel(
        quotesToday=quotes_today,
        quotesThisWeek=quotes_week,
        totalQuotedValue=money_required(Decimal(total_value or 0), currency),
        averageDistanceKm=Decimal(str(average_distance)) if average_distance is not None else None,
        topDestinations=[
            TopDestinationModel(name=str(name), count=int(count)) for name, count in top_rows
        ],
        needsReview=[
            NeedsReviewModel(
                id=quote.id,
                locationLabel=quote.resolved_label or quote.input_label,
                reason=quote.failure_code,
                createdAt=quote.created_at,
            )
            for quote in review_rows
        ],
        statusCounts={
            (status.value if hasattr(status, "value") else str(status)): int(count)
            for status, count in status_counts.items()
        },
    )


def _parse_day(value: str, *, start: bool) -> datetime:
    """Parse a ``YYYY-MM-DD`` filter into an aware UTC instant."""
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise AppError(
            ErrorCode.VALIDATION, f"“{value}” is not a date. Use YYYY-MM-DD.", details={"field": "date"}
        ) from exc
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC) + (
        timedelta(0) if start else timedelta(days=1) - timedelta(microseconds=1)
    )

