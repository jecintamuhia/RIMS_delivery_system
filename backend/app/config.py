"""Environment-driven configuration.

Every deployment knob is read from the environment (or a ``.env`` file). Nothing here has a
usable production default: secrets, provider credentials and the session key must be supplied.
See ``.env.example`` for the documented list.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
ProviderName = Literal["osm", "mapbox", "null"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,

        enable_decoding=False,
    )

    app_name: str = "RIMs Delivery Pricing API"
    environment: Environment = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True

    database_url: str = "sqlite+aiosqlite:///./rims_delivery.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    redis_url: SecretStr | None = None
    cache_ttl_geocode: int = 86_400
    cache_ttl_route: int = 3_600
    cache_max_entries: int = 5_000

    geocoding_provider: ProviderName = "osm"
    routing_provider: ProviderName = "osm"
    maps_api_key: SecretStr | None = None
    provider_base_url: str | None = None
    provider_timeout_seconds: float = 10.0
    provider_max_retries: int = 2
    provider_user_agent: str = "RIMsDeliveryPricing/1.0 (contact: ops@rims.example)"
    country_code: str = "ke"
    provider_bias_lat: float | None = None
    provider_bias_lng: float | None = None

    jwt_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    session_cookie_name: str = "rims_admin_session"
    session_max_age_seconds: int = 60 * 60 * 8
    session_https_only: bool = False
    csrf_protection: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_auth_requests: int = 10
    rate_limit_auth_window_seconds: int = 300

    rate_limit_geo_requests: int = 30
    rate_limit_geo_window_seconds: int = 60
    #: Honour X-Forwarded-For / X-Real-IP. Enable only behind a trusted reverse proxy,
    #: otherwise a caller can spoof its identity and evade the limiter.
    trust_forwarded_for: bool = False
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # ── geography / business configuration ───────────────────────────────────────
    service_area_min_lat: float = -5.0
    service_area_max_lat: float = 5.5
    service_area_min_lng: float = 33.0
    service_area_max_lng: float = 42.5
    default_currency: str = "KES"
    quote_expires_after_hours: int = 24
    max_quote_attempts: int = 5


    auto_seed_distance_pricing: bool = True
    default_distance_rate_per_km: Decimal = Decimal("150")


    dispatch_name: str = "RIMs Supplies and Hardware — Kenyatta Avenue, Naivasha"

    dispatch_latitude: float = -0.7256336
    dispatch_longitude: float = 36.4448417

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    return value
                if isinstance(decoded, list):
                    return decoded
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.environment != "production":
            return self
        missing = [
            name
            for name in ("session_secret", "jwt_secret")
            if getattr(self, name) is None or not getattr(self, name).get_secret_value()
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} must be set when ENVIRONMENT=production")
        if not self.session_https_only:
            raise ValueError("SESSION_HTTPS_ONLY must be true when ENVIRONMENT=production")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def effective_session_secret(self) -> str:
        secret = self.session_secret or self.jwt_secret
        if secret is None:
            raise RuntimeError("SESSION_SECRET or JWT_SECRET must be configured to use sessions")
        return secret.get_secret_value()

    @property
    def provider_key(self) -> str | None:
        return self.maps_api_key.get_secret_value() if self.maps_api_key else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Tests call ``get_settings.cache_clear()`` after patching env."""
    return Settings()
