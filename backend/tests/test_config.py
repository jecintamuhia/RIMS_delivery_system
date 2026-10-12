from __future__ import annotations

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("raw_origins", "expected"),
    [
        ("http://localhost:5173,http://localhost:8080", ["http://localhost:5173", "http://localhost:8080"]),
        ('["https://rims.example", "https://admin.rims.example"]', ["https://rims.example", "https://admin.rims.example"]),
    ],
)
def test_cors_origins_accept_csv_and_json_environment_values(
    monkeypatch: pytest.MonkeyPatch, raw_origins: str, expected: list[str]
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", raw_origins)

    settings = Settings(_env_file=None)

    assert settings.cors_origins == expected
