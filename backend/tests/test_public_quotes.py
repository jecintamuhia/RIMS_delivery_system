"""End-to-end quote pipeline.

The central guarantee under test: a quote is priced from the provider's real road distance and
RIMs' configured rules, and when any step cannot be completed the quote says so rather than
inventing a figure.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from app.models import Destination, DestinationAlias, PricingRule, PricingVersion, PricingVersionStatus

#: The RIMs dispatch point, which doubles as the test's reference location.
DISPATCH_LAT = -0.7256336
DISPATCH_LNG = 36.4448417


async def _configure_priced_nakuru(client: AsyncClient, *, activate: bool = True) -> tuple[str, str]:
    """Create a destination and a flat 1,500 KES price for it."""
    created = await client.post(
        "/api/v1/admin/destinations",
        json={"name": "Nakuru", "code": "NAK", "aliases": ["Nakuru Town", "Nakuru municipality"]},
    )
    assert created.status_code == 201, created.text
    destination_id = created.json()["id"]

    version = await client.post(
        "/api/v1/admin/pricing-versions",
        json={"label": "2026-01", "effectiveFrom": "2026-01-01"},
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["id"]

    rule = await client.post(
        "/api/v1/admin/pricing-rules",
        json={"destinationId": destination_id, "basePrice": "1500.00", "versionId": version_id},
    )
    assert rule.status_code == 201, rule.text

    if activate:
        # Review then activate, the way an administrator does it.
        approved = await client.post(
            f"/api/v1/admin/pricing-versions/{version_id}/confirm-validation", json={}
        )
        assert approved.status_code == 200, approved.text
        activated = await client.post(f"/api/v1/admin/pricing-versions/{version_id}/activate")
        assert activated.status_code == 200, activated.text
    return destination_id, version_id


async def _run_pipeline(client: AsyncClient) -> dict[str, Any]:
    """Create a quote and read back the pipeline result.

    ``POST /public/quotes`` registers a background task, and Starlette runs it before the response
    is returned, so the quote has already reached a terminal state by the time we read it. The
    test therefore observes the same pipeline the browser polls, rather than driving it by hand.
    """
    created = await client.post(
        "/api/v1/public/quotes",
        json={"position": {"lat": DISPATCH_LAT, "lng": DISPATCH_LNG}, "label": "Nakuru", "resolved": True},
    )
    assert created.status_code == 202, created.text
    quote_id = created.json()["id"]

    final = await client.get(f"/api/v1/public/quotes/{quote_id}")
    assert final.status_code == 200, final.text
    body: dict[str, Any] = final.json()
    return body


async def test_quote_is_priced_from_configured_rule(client: AsyncClient) -> None:
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)

    assert body["status"] == "completed", body
    assert Decimal(str(body["fee"]["amount"])) == Decimal("1500.00")
    assert body["fee"]["currency"] == "KES"
    assert body["destination"]["name"] == "Nakuru"
    # The stub provider returned 100 km; the quote must report exactly that, not a computed value.
    assert Decimal(str(body["distanceKm"])) == Decimal("100.00")


async def test_every_step_completes_in_order(client: AsyncClient) -> None:
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)

    assert [step["key"] for step in body["steps"]] == [
        "location",
        "route",
        "destination",
        "pricing",
        "estimate",
    ]
    assert all(step["state"] == "completed" for step in body["steps"]), body["steps"]


async def test_customer_view_has_no_breakdown(client: AsyncClient) -> None:
    """The public quote must not expose internal pricing detail."""
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)
    assert "breakdown" not in body
    assert "calculations" not in body


async def test_unpriced_destination_reports_no_rule_not_a_price(client: AsyncClient) -> None:
    """A destination with no price must fail honestly."""
    destination = await client.post(
        "/api/v1/admin/destinations", json={"name": "Nakuru", "code": "NAK", "aliases": ["Nakuru Town"]}
    )
    assert destination.status_code == 201, destination.text

    # Configure a version with a price for a *different* destination so pricing is not unconfigured
    # overall, but Nakuru itself has no rule.
    await client.post(
        "/api/v1/admin/pricing-versions", json={"label": "2026-01", "effectiveFrom": "2026-01-01"}
    )
    other = await client.post(
        "/api/v1/admin/destinations", json={"name": "Eldoret", "code": "ELD"}
    )
    versions = (await client.get("/api/v1/admin/pricing-versions")).json()
    rule = await client.post(
        "/api/v1/admin/pricing-rules",
        json={
            "destinationId": other.json()["id"],
            "basePrice": "900.00",
            "versionId": versions[0]["id"],
        },
    )
    assert rule.status_code == 201, rule.text
    await client.post(f"/api/v1/admin/pricing-versions/{versions[0]['id']}/confirm-validation", json={})
    await client.post(f"/api/v1/admin/pricing-versions/{versions[0]['id']}/activate")

    body = await _run_pipeline(client)
    assert body["status"] == "needs_review", body
    assert body["failure"]["code"] == "NO_PRICING_RULE"
    assert body["fee"] is None
    steps = {step["key"]: step["state"] for step in body["steps"]}
    assert steps["pricing"] == "failed"
    # The estimate must not claim to have run when it never did.
    assert steps["estimate"] == "pending"


async def test_no_destinations_configured_is_not_a_silent_price(client: AsyncClient) -> None:
    body = await _run_pipeline(client)
    assert body["status"] == "needs_review"
    assert body["failure"]["code"] == "DESTINATION_UNSUPPORTED"
    assert body["fee"] is None


async def test_quote_outside_service_area_is_rejected(anon_client: AsyncClient) -> None:
    """A pin outside the configured service area cannot be priced and must not be accepted."""
    response = await anon_client.post(
        "/api/v1/public/quotes",
        json={"position": {"lat": 48.85, "lng": 2.35}, "label": "Paris"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_LOCATION"


async def test_accept_requires_a_price(client: AsyncClient) -> None:
    """Accepting an unpriced quote would record agreement to a number never produced."""
    body = await _run_pipeline(client)
    assert body["status"] == "needs_review"
    response = await client.post(f"/api/v1/public/quotes/{body['id']}/accept")
    assert response.status_code == 422
    assert response.json()["code"] == "MANUAL_REVIEW"


async def test_accept_a_priced_quote(client: AsyncClient) -> None:
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)
    accepted = await client.post(f"/api/v1/public/quotes/{body['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"


async def test_recalculate_reruns_the_pipeline(client: AsyncClient) -> None:
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)
    quote_id = body["id"]

    response = await client.post(f"/api/v1/public/quotes/{quote_id}/recalculate")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processing"
    assert all(step["state"] == "pending" for step in response.json()["steps"])


async def test_admin_sees_the_breakdown_the_customer_did_not(client: AsyncClient) -> None:
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)

    detail = await client.get(f"/api/v1/admin/quotes/{body['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["breakdown"]["basePrice"]["amount"] == "1500.00"
    assert payload["breakdown"]["pricingVersion"] == "2026-01"
    assert len(payload["calculations"]) == 1
    assert payload["destinationMatchMethod"] == "alias"


async def test_quote_history_is_immutable_after_reprice(client: AsyncClient) -> None:
    """A second pricing run must not rewrite the first calculation."""
    await _configure_priced_nakuru(client)
    body = await _run_pipeline(client)
    quote_id = body["id"]

    await client.post(f"/api/v1/public/quotes/{quote_id}/recalculate")

    detail = (await client.get(f"/api/v1/admin/quotes/{quote_id}")).json()
    assert len(detail["calculations"]) == 2, "each run should append, not overwrite"
    amounts = {Decimal(str(calc["total"]["amount"])) for calc in detail["calculations"]}
    assert amounts == {Decimal("1500.00")}


@pytest.mark.parametrize("missing", ["position", "label"])
async def test_quote_request_validation(anon_client: AsyncClient, missing: str) -> None:
    payload: dict[str, Any] = {"position": {"lat": DISPATCH_LAT, "lng": DISPATCH_LNG}, "label": "Nakuru"}
    payload.pop(missing)
    response = await anon_client.post("/api/v1/public/quotes", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


async def test_public_config_needs_no_authentication(anon_client: AsyncClient, origin: Any) -> None:
    response = await anon_client.get("/api/v1/public/config")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dispatch"]["name"] == "RIMs Supplies and Hardware — Kenyatta Avenue, Naivasha"
    assert body["dispatch"]["lat"] == pytest.approx(DISPATCH_LAT)
    assert body["map"]["center"]["lng"] == pytest.approx(DISPATCH_LNG)


async def test_location_search(anon_client: AsyncClient) -> None:
    found = await anon_client.get("/api/v1/public/locations/search", params={"q": "Nakuru"})
    assert found.status_code == 200, found.text
    assert [item["label"] for item in found.json()] == ["Nakuru"]

    missing = await anon_client.get("/api/v1/public/locations/search", params={"q": "Atlantis"})
    assert missing.status_code == 200
    assert missing.json() == []


async def test_route_preview_reports_distance_without_a_price(anon_client: AsyncClient) -> None:
    """The locate step may show distance and travel time, but never a price before quoting."""
    response = await anon_client.get(
        "/api/v1/public/route",
        params={"lat": DISPATCH_LAT, "lng": DISPATCH_LNG},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(str(body["distanceKm"])) > 0
    assert body["durationMinutes"] >= 1
    assert "fee" not in body and "price" not in body
    assert set(body) <= {"distanceKm", "durationMinutes", "route"}


async def test_route_preview_refuses_a_point_outside_the_service_area(
    anon_client: AsyncClient,
) -> None:
    """Routing is bounded by the same service area the quote pipeline uses."""
    response = await anon_client.get(
        "/api/v1/public/route",
        params={"lat": 48.85, "lng": 2.35},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_LOCATION"


async def test_unknown_quote_is_not_found(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/api/v1/public/quotes/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_enums_round_trip_through_the_database(session: Any) -> None:
    """Guards the enum persistence contract: lowercase values, not member names."""
    from sqlalchemy import text

    version = PricingVersion(
        label="enum-check",
        status=PricingVersionStatus.ACTIVE,
        effective_from=date(2026, 1, 1),
    )
    session.add(version)
    await session.flush()
    destination = Destination(name="Kisumu", code="KIS")
    session.add(destination)
    await session.flush()
    session.add(
        PricingRule(
            version_id=version.id,
            destination_id=destination.id,
            scope_key=f"{destination.id}|*|*",
            base_price=Decimal("1000.00"),
            effective_from=date(2026, 1, 1),
        )
    )
    session.add(DestinationAlias(destination_id=destination.id, alias="Kisumu City"))
    await session.commit()

    status = await session.execute(text("select status from pricing_versions"))
    assert status.scalar_one() == "active"
    adjustment = await session.execute(text("select adjustment_type from pricing_rules"))
    assert adjustment.scalar_one() == "none"
