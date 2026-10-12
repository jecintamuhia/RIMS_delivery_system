"""Pricing review gate: validation findings,  approval,  and activation ordering.

The tests that matter here are the negative ones. RIMs' real list imports cleanly and validates
cleanly,  so a suite of happy paths would prove nothing; what has to hold is that a broken list
cannot reach a customer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Destination, PricingRule, PricingVersion, PricingVersionStatus
from app.services.pricing.validation import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    ValidationReport,
    validate_version,
)


def _codes(report: ValidationReport, severity: str = SEVERITY_ERROR) -> set[str]:
    return {item.code for item in report.findings if item.severity == severity}


async def _make_version(session: AsyncSession, label: str, rules: list[tuple[str, str]], **kwargs: Any) -> PricingVersion:
    """``rules`` is ``(destination_name, base_price)``."""
    version = PricingVersion(
        label=label,
        status=PricingVersionStatus.DRAFT,
        effective_from=kwargs.pop("effective_from", date(2026, 10, 5)),
        currency=kwargs.pop("currency", "KES"),
        **kwargs,
    )
    session.add(version)
    await session.flush()
    for name, price in rules:
        destination = await session.scalar(select(Destination).where(Destination.name == name))
        assert destination is not None, name
        session.add(
            PricingRule(
                version_id=version.id,
                destination_id=destination.id,
                base_price=price,
                scope_key=f"{destination.id}|*|*",
                effective_from=version.effective_from,
            )
        )
    # Committed, not just flushed: the HTTP tests need the rows visible to the app's own session.
    await session.commit()
    await session.refresh(version)
    return version


@pytest.fixture
async def priced_destination(session: AsyncSession) -> Destination:
    destination = Destination(
        name="KIRIMIRI", code="KIRIMIRI", latitude=-0.53, longitude=36.15, is_active=True
    )
    session.add(destination)
    await session.flush()
    return destination


@pytest.fixture
async def unpinned_destination(session: AsyncSession) -> Destination:
    """A destination with no coordinates at all - only matchable by exact name."""
    destination = Destination(name="G!TUAMBA", code="G-TUAMBA", is_active=True)
    session.add(destination)
    await session.flush()
    return destination


# ── validation ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clean_version_is_valid(session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Clean list", [("KIRIMIRI", "1500")])
    report = await validate_version(session, version)
    assert report.valid is True
    assert report.errors == []
    assert report.rule_count == 1
    assert report.destination_count == 1
    assert report.summary.endswith("can be activated.")


@pytest.mark.asyncio
async def test_version_with_no_rules_blocks_activation(session: AsyncSession) -> None:
    version = await _make_version(session, "Empty list", [])
    report = await validate_version(session, version)
    assert report.valid is False
    assert "no_rules" in _codes(report)
    assert "1 problem(s) must be fixed" in report.summary


@pytest.mark.asyncio
async def test_two_prices_for_one_destination_is_ambiguous(session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Duplicated", [])
    session.add(
        PricingRule(
            version_id=version.id,
            destination_id=priced_destination.id,
            base_price="1500",
            scope_key=f"{priced_destination.id}|*|*",
            effective_from=version.effective_from,
        )
    )
    await session.flush()
    # A second rule for the same destination with a different scope: allowed by the schema,
    # rejected by validation,  because we cannot say which price RIMs meant.
    session.add(
        PricingRule(
            version_id=version.id,
            destination_id=priced_destination.id,
            base_price="1200",
            scope_key=f"{priced_destination.id}|road_a|*",
            effective_from=version.effective_from,
        )
    )
    await session.flush()
    await session.refresh(version)

    report = await validate_version(session,  version)
    assert report.valid is False
    assert "duplicate_destination_price" in _codes(report)
    assert any(item.destination_name == "KIRIMIRI" for item in report.errors)


@pytest.mark.asyncio
async def test_rule_outside_version_window_blocks(session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Out of window", [("KIRIMIRI", "1500")])
    version.effective_from = date(2026, 1, 1)
    version.effective_to = date(2026, 1, 31)
    rule = version.rules[0]
    rule.effective_from = date(2026, 6, 1)
    await session.flush()
    await session.refresh(version)

    report = await validate_version(session, version)
    assert report.valid is False
    assert "rule_outside_version_window" in _codes(report)


@pytest.mark.asyncio
async def test_future_dated_rule_inside_window_is_allowed(session: AsyncSession, priced_destination: Destination) -> None:
    """A price that starts later inside the version's window is deliberate, not broken."""
    version = await _make_version(session, "Phased", [("KIRIMIRI", "1500")])
    version.effective_from = date(2026, 1, 1)
    version.effective_to = date(2026, 12, 31)
    version.rules[0].effective_from = date(2026, 11, 1)
    await session.flush()
    await session.refresh(version)

    report = await validate_version(session, version)
    assert report.valid is True
    assert "rule_outside_version_window" not in _codes(report)


@pytest.mark.asyncio
async def test_unusual_name_is_a_warning_not_an_error(session: AsyncSession, unpinned_destination: Destination) -> None:
    """RIMs' own list contains ``G!TUAMBA``. We report it; we never block on it or rewrite it."""
    version = await _make_version(session, "RIMs list", [("G!TUAMBA", "2000")])
    report = await validate_version(session, version)
    assert report.valid is True
    assert "unusual_destination_name" in _codes(report, SEVERITY_WARNING)
    assert any(item.destination_name == "G!TUAMBA" for item in report.warnings)


@pytest.mark.asyncio
async def test_vague_name_is_a_warning(session: AsyncSession) -> None:
    destination = Destination(name="TOWN AREA", code="TOWN-AREA", latitude=-0.5, longitude=36.2, is_active=True)
    session.add(destination)
    await session.flush()
    version = await _make_version(session, "Vague", [("TOWN AREA", "1000")])

    report = await validate_version(session, version)
    assert report.valid is True
    assert "vague_destination_name" in _codes(report, SEVERITY_WARNING)


@pytest.mark.asyncio
async def test_missing_geography_is_a_warning(session: AsyncSession, unpinned_destination: Destination) -> None:
    version = await _make_version(session, "No geo", [("G!TUAMBA", "2000")])
    report = await validate_version(session, version)
    assert report.valid is True
    assert "no_geography" in _codes(report, SEVERITY_WARNING)


@pytest.mark.asyncio
async def test_geography_present_means_no_geo_warning(session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Has geo", [("KIRIMIRI", "1500")])
    report = await validate_version(session, version)
    assert "no_geography" not in _codes(report, SEVERITY_WARNING)


@pytest.mark.asyncio
async def test_validation_does_not_write(session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Read only", [("KIRIMIRI", "1500")])
    await validate_version(session, version)
    await session.refresh(version)
    assert version.validated_at is None
    assert version.validated_by_id is None


# ── HTTP: validate, approve, activate ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_endpoint_reports_findings(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Needs review", [("KIRIMIRI", "1500")])

    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/validate"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["versionId"] == version.id
    assert body["ruleCount"] == 1
    assert body["summary"]


@pytest.mark.asyncio
async def test_failing_validation_returns_200_with_findings(client: AsyncClient, session: AsyncSession) -> None:
    """A failed *check* is a successful *request*; otherwise the UI cannot show why it failed."""
    version = await _make_version(session, "Broken", [])
    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/validate"
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any(item["code"] == "no_rules" for item in response.json()["findings"])


@pytest.mark.asyncio
async def test_activate_requires_approval(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Unapproved", [("KIRIMIRI", "1500")])

    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/activate"
    )
    assert response.status_code == 422
    assert "not been approved" in response.json()["message"]

    listed = await client.get("/api/v1/admin/pricing-versions")
    statuses = {row["id"]: row["status"] for row in listed.json()}
    assert statuses[version.id] == "draft", "a blocked activation must leave the version a draft"


@pytest.mark.asyncio
async def test_confirm_validation_records_the_reviewer(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Approved", [("KIRIMIRI", "1500")])
    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
        json={"note": "Checked against RIMs' 5 Oct list"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["validatedAt"] is not None
    assert body["validationNote"] == "Checked against RIMs' 5 Oct list"

    await session.refresh(version)
    assert version.validated_by_id is not None


@pytest.mark.asyncio
async def test_confirm_validation_rejects_a_broken_version(client: AsyncClient, session: AsyncSession) -> None:
    version = await _make_version(session, "Broken", [])
    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
        json={},
    )
    assert response.status_code == 422
    assert "problem(s)" in response.json()["message"]


@pytest.mark.asyncio
async def test_approved_version_activates(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    version = await _make_version(session, "Good to go", [("KIRIMIRI", "1500")])
    await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
        json={},
    )
    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/activate"
    )
    assert response.status_code == 200
    assert response.json()["ruleCount"] == 1


@pytest.mark.asyncio
async def test_activate_retires_the_previous_version(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    first = await _make_version(session, "First", [("KIRIMIRI", "1500")])
    second = await _make_version(session, "Second", [("KIRIMIRI", "1700")])

    for version in (first, second):
        await client.post(
            f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
                json={},
        )
        await client.post(
            f"/api/v1/admin/pricing-versions/{version.id}/activate"
        )

    await session.refresh(first)
    await session.refresh(second)
    assert second.status == PricingVersionStatus.ACTIVE
    assert first.status == PricingVersionStatus.RETIRED


@pytest.mark.asyncio
async def test_retiring_clears_the_approval_stamp(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    """A stale approval must never authorise a future change to the same version."""
    version = await _make_version(session, "Retired", [("KIRIMIRI", "1500")])
    await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
        json={},
    )
    await client.post(f"/api/v1/admin/pricing-versions/{version.id}/activate")

    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/retire"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["validatedAt"] is None
    assert body["validatedBy"] is None


@pytest.mark.asyncio
async def test_edited_version_cannot_reuse_the_old_approval(client: AsyncClient, session: AsyncSession, priced_destination: Destination) -> None:
    """The activation-time revalidation is the real gate; approval alone is not a licence."""
    version = await _make_version(session, "Edited after review", [("KIRIMIRI", "1500")])
    await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/confirm-validation",
        json={},
    )
    # A price that predates the version it belongs to can never apply.
    version.rules[0].effective_from = date(2020, 1, 1)
    await session.commit()

    response = await client.post(
        f"/api/v1/admin/pricing-versions/{version.id}/activate"
    )
    assert response.status_code == 422
    assert "problem(s)" in response.json()["message"]
