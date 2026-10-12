"""Rate-limit budgets.

Location search and route previews each spend a third-party geocoding or routing call, so
they carry their own tighter bucket than ordinary public reads, and login stays the strictest
of all.
"""

from __future__ import annotations

from app.config import Settings
from app.ratelimit import budget_for


def test_geo_paths_get_a_separate_tighter_budget() -> None:
    settings = Settings()

    bucket, limit, window = budget_for("/api/v1/public/route", settings)
    assert (bucket, limit, window) == ("geo", 30, 60)

    search_bucket, *_ = budget_for("/api/v1/public/locations/search", settings)
    assert search_bucket == "geo"

    public_bucket, public_limit, _ = budget_for("/api/v1/public/quotes", settings)
    assert public_bucket == "public"
    assert public_limit > limit


def test_login_keeps_the_strictest_budget() -> None:
    settings = Settings()
    bucket, limit, window = budget_for("/api/v1/auth/login", settings)
    assert (bucket, limit, window) == ("auth", 10, 300)
