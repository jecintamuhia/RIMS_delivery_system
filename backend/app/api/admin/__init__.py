"""Admin API surface.

One aggregator so ``app.main`` includes a single router. Each submodule owns one area and
declares its own role requirements per endpoint, so a viewer can read while only an editor or
admin can write.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin import destinations, dynamic_pricing, pricing, quotes, reference, users

router = APIRouter()

# Mounted in this order so the OpenAPI schema groups resources logically.
router.include_router(quotes.router)
router.include_router(destinations.router)
router.include_router(pricing.router)
router.include_router(dynamic_pricing.router)
router.include_router(reference.router)
router.include_router(users.router)

__all__ = ["router"]
