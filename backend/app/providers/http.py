"""Shared HTTP plumbing for provider adapters.

One :class:`httpx.AsyncClient` per process, bounded timeouts, bounded retries with jittered
backoff, and a circuit breaker so a provider outage degrades fast into a clean
``ROUTING_UNAVAILABLE`` instead of piling up timeouts. Provider failures are logged with the
provider name and reason, never with the API key.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from types import TracebackType
from typing import Any, Self

import httpx

from app.config import get_settings
from app.observability import log_event
from app.providers.base import ProviderError, ProviderNoResult

logger = logging.getLogger("app.providers.http")


class CircuitBreaker:
    """Trips after ``failure_threshold`` consecutive failures, re-probing after ``reset_seconds``."""

    def __init__(self, failure_threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_seconds:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            log_event(logger, logging.WARNING, "provider circuit opened", failures=self._failures)


class ProviderHttpClient:
    """Async HTTP client with retry + circuit breaker, shared by provider adapters."""

    def __init__(self, provider: str) -> None:
        settings = get_settings()
        self.provider = provider
        self._timeout = httpx.Timeout(settings.provider_timeout_seconds, connect=5.0)
        self._max_retries = settings.provider_max_retries
        self._user_agent = settings.provider_user_agent
        self._breaker = CircuitBreaker()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            raise RuntimeError("ProviderHttpClient used outside its async context")
        if self._breaker.is_open:
            log_event(logger, logging.WARNING, "provider circuit open; not calling", provider=self.provider)
            raise ProviderError(
                "provider temporarily unavailable", provider=self.provider, retryable=False, cause="circuit_open"
            )

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, params=params, headers={"User-Agent": self._user_agent})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                log_event(
                    logger,
                    logging.WARNING,
                    "provider request failed",
                    provider=self.provider,
                    attempt=attempt + 1,
                    reason=type(exc).__name__,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                break
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ProviderError(
                    f"provider returned HTTP {response.status_code}",
                    provider=self.provider,
                    cause=f"http_{response.status_code}",
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "provider returned error status",
                    provider=self.provider,
                    status=response.status_code,
                    attempt=attempt + 1,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                break
            if response.status_code == 404:
                raise ProviderNoResult("provider has no record for this location", self.provider)
            if response.is_error:
                raise ProviderError(
                    f"provider returned HTTP {response.status_code}",
                    provider=self.provider,
                    retryable=False,
                    cause=f"http_{response.status_code}",
                )
            self._breaker.record_success()
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(
                    "provider returned a malformed response",
                    provider=self.provider,
                    retryable=False,
                    cause="invalid_json",
                ) from exc

        self._breaker.record_failure()
        raise ProviderError(
            "provider did not return a usable response",
            provider=self.provider,
            retryable=True,
            cause=type(last_error).__name__ if last_error else "unknown",
        )

    @staticmethod
    def _backoff(attempt: int) -> float:
        delay: float = 0.25 * float(2**attempt)
        jitter: float = 0.7 + random.random() * 0.6
        return min(2.0, delay) * jitter
