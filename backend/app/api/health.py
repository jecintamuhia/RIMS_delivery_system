"""Liveness and readiness probes.

``/health`` answers "is this process up" and must never depend on an external system, so it is
safe for a load balancer. ``/ready`` answers "can this instance serve traffic" and does check the
database, the cache backend, the provider configuration and whether any pricing exists at all -
the last one being the honest signal that the system is installed but cannot yet price anything.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.admin_schemas import HealthModel, ReadinessModel
from app.api.deps import SessionDep
from app.cache import cache_backend_name, get_cache
from app.config import get_settings
from app.models import Destination, PricingRule, PricingVersion, PricingVersionStatus
from app.observability import log_event
from app.providers import get_providers

logger = logging.getLogger("app.api.health")

router = APIRouter(tags=["health"])

VERSION = "1.0.0"


@router.get("/health", response_model=HealthModel, summary="Liveness probe")
async def health() -> HealthModel:
    return HealthModel(status="ok", version=VERSION, environment=get_settings().environment)


@router.get("/ready", response_model=ReadinessModel, summary="Readiness probe")
async def ready(session: SessionDep) -> ReadinessModel:
    checks: dict[str, str] = {}
    ready_state = True

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("readiness: database check failed: %s", type(exc).__name__)
        checks["database"] = "error"
        ready_state = False

    cache_name = "uninitialised"
    if ready_state:
        try:
            await get_cache()
            cache_name = cache_backend_name()
            checks["cache"] = "ok"
        except Exception as exc:
            logger.warning("readiness: cache check failed: %s", type(exc).__name__)
            checks["cache"] = "degraded"
            cache_name = "unavailable"

    geocoder, router_provider = get_providers()
    providers = {geocoder.name: "configured", router_provider.name: "configured"}
    if getattr(geocoder, "reason", None) or getattr(router_provider, "reason", None):
        ready_state = False
        checks["providers"] = "unavailable"

    pricing_version: str | None = None
    destination_count = 0
    pricing_configured = False
    if ready_state:
        try:
            destination_count = int(
                await session.scalar(select(func.count(Destination.id)).where(Destination.is_active.is_(True)))
                or 0
            )
            active = await session.scalar(
                select(PricingVersion).where(PricingVersion.status == PricingVersionStatus.ACTIVE).limit(1)
            )
            if active is not None:
                pricing_version = active.label
                rule_count = int(
                    await session.scalar(
                        select(func.count(PricingRule.id)).where(
                            PricingRule.version_id == active.id, PricingRule.is_active.is_(True)
                        )
                    )
                    or 0
                )
                pricing_configured = rule_count > 0
            checks["pricing"] = "ok" if pricing_configured else "not_configured"
        except Exception as exc:
            logger.warning("readiness: pricing check failed: %s", type(exc).__name__)
            checks["pricing"] = "error"
            ready_state = False

    if ready_state:
        log_event(logger, logging.INFO, "readiness ok", cache=cache_name, pricing=pricing_configured)

    return ReadinessModel(
        status="ok" if ready_state else "degraded",
        ready=ready_state,
        version=VERSION,
        environment=get_settings().environment,
        checks=checks,
        cache=cache_name,
        providers=providers,
        pricingConfigured=pricing_configured,
        activePricingVersion=pricing_version,
        destinationCount=destination_count,
        timestamp=datetime.now(UTC),
    )
