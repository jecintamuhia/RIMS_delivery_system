"""Rate limiting.

A fixed-window counter per client key, backed by an in-process map (sufficient for a single
instance) with an optional Redis backend. Authenticated and unauthenticated clients get
separate budgets: login attempts are limited far more aggressively than quote requests, which
are the public entry point.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import Settings, get_settings

#: Endpoints that must not be brute-forced, mapped to a budget name.
_AUTH_PATHS = ("/auth/login",)

#: Endpoints that spend a third-party geocoding or routing call on every cache miss. They get
#: a separate, tighter budget so one caller paging through locations cannot exhaust the
#: provider quota (or the bill) behind the ordinary public API.
_GEO_PATHS = ("/public/locations/", "/public/route")


class RateLimitDecision:
    __slots__ = ("allowed", "limit", "remaining", "retry_after")

    def __init__(self, allowed: bool, limit: int, remaining: int, retry_after: int) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.retry_after = retry_after


class FixedWindowLimiter:
    """In-process fixed-window limiter. Thread-safe via the asyncio lock-free GIL assumption
    for single-threaded asyncio; adequate for a modular monolith on one instance."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, key: str, bucket: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        hits = self._hits[(bucket, key)]
        cutoff = now - window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            return RateLimitDecision(False, limit, 0, retry_after)
        hits.append(now)
        return RateLimitDecision(True, limit, limit - len(hits), 0)

    def reset(self) -> None:
        self._hits.clear()


_limiter = FixedWindowLimiter()


def client_key(request: Request) -> str:
    """Identify the caller.

    ``X-Forwarded-For`` is only honoured when the deployment opts in via
    ``TRUST_FORWARDED_FOR=true``, because trusting it unconditionally lets a caller forge its
    own identity and bypass the limit.
    """
    settings = get_settings()
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip and settings.trust_forwarded_for:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def budget_for(path: str, settings: Settings) -> tuple[str, int, int]:
    if any(path.endswith(suffix) for suffix in _AUTH_PATHS):
        return "auth", settings.rate_limit_auth_requests, settings.rate_limit_auth_window_seconds
    if any(suffix in path for suffix in _GEO_PATHS):
        return "geo", settings.rate_limit_geo_requests, settings.rate_limit_geo_window_seconds
    return "public", settings.rate_limit_requests, settings.rate_limit_window_seconds


def enforce(request: Request) -> RateLimitDecision | None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return None
    bucket, limit, window = budget_for(request.url.path, settings)
    return _limiter.check(client_key(request), bucket, limit=limit, window_seconds=window)


def reset_limiter() -> None:
    _limiter.reset()
