"""First-run bootstrap.

Three jobs, all idempotent so they are safe to run on every start:

* create the first admin account from ``BOOTSTRAP_ADMIN_EMAIL`` / ``BOOTSTRAP_ADMIN_PASSWORD``
  when configured, so a fresh deployment is not left with no way in;
* ensure the RIMs dispatch point exists, because without an origin no quote can be routed;
* seed a default per-kilometre distance rate, so a delivery location outside the official
  destination price list is still priced automatically instead of being refused.

Deliberately **not** seeded: destinations, aliases, road types, vehicles and fixed prices. RIMs
owns that data, it arrives through the import workflow, and inventing it would produce a system
that confidently quotes amounts RIMs never agreed to.

Two exceptions stand, and both are business data RIMs supplied rather than invented by this
module. The dispatch point is a single address RIMs gave us (``Settings.dispatch_*``, defaulting
to the Kenyatta Avenue premises in Naivasha), and a system that cannot route cannot be used at
all. The distance rate is the fallback RIMs asked for: a location with no official price is
charged per kilometre (``Settings.default_distance_rate_per_km``, default 150 KES/km). Both are
seeded once - the distance rate only on a genuinely fresh install, never over an existing one -
and are thereafter owned by the admin UI.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import (
    DeliveryOrigin,
    DynamicPricingVersion,
    PricingVersionStatus,
    Role,
    User,
)
from app.observability import log_event
from app.security import hash_password

#: Label for the seeded fallback rate. Fixed, so the audit trail and the admin list agree.
DEFAULT_DISTANCE_LABEL = "Standard distance rate (auto)"

logger = logging.getLogger("app.services.bootstrap")

#: The RIMs dispatch point. Never a guessed depot: this is the address RIMs supplied, and an
#: administrator changes it from Admin > Settings when the premises change.
def _rims_dispatch(settings: Settings) -> DeliveryOrigin:
    return DeliveryOrigin(
        name=settings.dispatch_name,
        latitude=settings.dispatch_latitude,
        longitude=settings.dispatch_longitude,
        is_default=True,
    )


async def ensure_bootstrap_admin(session: AsyncSession, settings: Settings | None = None) -> User | None:
    """Create the initial admin if the environment names one and no users exist."""
    settings = settings or get_settings()
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email or password is None:
        return None

    normalised = email.strip().casefold()
    existing = await session.scalar(select(User).where(User.email == normalised))
    if existing is not None:
        return None

    user_count = int(await session.scalar(select(func.count(User.id))) or 0)
    if user_count:
        # Accounts already exist, so bootstrap has done its job. Creating a second admin from a
        # stale environment variable would be an unexpected privilege grant.
        return None

    user = User(
        email=normalised,
        full_name="RIMs administrator",
        password_hash=hash_password(password.get_secret_value()),
        role=Role.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    log_event(logger, logging.WARNING, "bootstrap admin created", user_id=user.id)
    return user


async def ensure_origin(session: AsyncSession, settings: Settings | None = None) -> DeliveryOrigin:
    """Return the dispatch origin, creating RIMs' real premises the first time.

    Idempotent, and never overwrites an origin an administrator has already configured: a stock
    start must not silently relocate a live depot on the next restart.
    """
    settings = settings or get_settings()
    origin = await session.scalar(
        select(DeliveryOrigin)
        .where(DeliveryOrigin.is_active.is_(True))
        .order_by(DeliveryOrigin.is_default.desc(), DeliveryOrigin.created_at)
        .limit(1)
    )
    if origin is not None:
        return origin

    dispatch = _rims_dispatch(settings)
    session.add(dispatch)
    await session.flush()
    log_event(
        logger,
        logging.WARNING,
        "no delivery origin configured; created the RIMs dispatch point from settings "
        "(change it in Admin > Settings if RIMs moves premises)",
        origin_id=dispatch.id,
    )
    return dispatch


async def ensure_default_distance_pricing(
    session: AsyncSession, settings: Settings | None = None
) -> DynamicPricingVersion | None:
    """Seed the per-kilometre fallback rate on a genuinely fresh install.

    "Fresh" means *no* distance pricing configuration exists at all - active, retired or draft.
    The moment any row exists, RIMs has taken ownership of this model, and re-seeding would
    either silently re-enable pricing an operator deliberately switched off or resurrect a rate
    they replaced. So the seed happens exactly once and never over an existing configuration.

    The seeded row is ``active`` (not a draft) on purpose: it is meant to answer quotes
    immediately. It carries a fixed label and a note explaining where it came from, and can be
    replaced like any other rate through Admin > Dynamic pricing.
    """
    settings = settings or get_settings()
    if not settings.auto_seed_distance_pricing:
        return None

    existing = int(await session.scalar(select(func.count(DynamicPricingVersion.id))) or 0)
    if existing:
        return None

    row = DynamicPricingVersion(
        label=DEFAULT_DISTANCE_LABEL,
        status=PricingVersionStatus.ACTIVE,
        base_rate_per_km=settings.default_distance_rate_per_km,
        fuel_adjustment_percent=Decimal("0"),
        currency=settings.default_currency,
        activated_at=datetime.now(UTC),
        notes=(
            "Seeded automatically so deliveries outside the official destination price list are "
            "priced per kilometre. Replace it by creating and activating a new rate in "
            "Admin > Dynamic pricing."
        ),
    )
    session.add(row)
    await session.flush()
    log_event(
        logger,
        logging.WARNING,
        "no distance pricing configured; seeded the default per-kilometre rate "
        "(change it in Admin > Dynamic pricing)",
        base_rate_per_km=str(settings.default_distance_rate_per_km),
        currency=settings.default_currency,
    )
    return row


async def run(session: AsyncSession, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    user = await ensure_bootstrap_admin(session, settings)
    await ensure_origin(session)
    await ensure_default_distance_pricing(session, settings)
    await session.commit()
    del user
    log_event(logger, logging.INFO, "bootstrap complete", at=datetime.now(UTC).isoformat())
