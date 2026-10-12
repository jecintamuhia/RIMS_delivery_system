"""Distance-based pricing (model B) and the wall between it and RIMs' fixed price list.

The guarantee under test is not "the maths works" but "the two models never bleed into each
other":

* a location with an official RIMs price is always quoted that price, even when a distance
  rate is active and would have said something else;
* a location outside the price list is quoted from its real road distance only when an admin
  has configured a distance rate, and refused honestly when none exists;
* a distance-based quote records which model priced it and every input of the calculation,
  and never writes a dynamic configuration id into the fixed-version foreign key.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.main import create_app
from app.models import DynamicPricingVersion, PricingVersionStatus
from app.services.pricing import engine
from app.services.pricing.models import AdjustmentKind, DynamicPricingConfig, PricingContext

#: The RIMs dispatch point, which doubles as the test's reference location.
DISPATCH_LAT = -0.7256336
DISPATCH_LNG = 36.4448417

PASSWORD = "correct-horse-battery"


# ------------------------------------------------------------------ engine (model B)


def _context(distance: str | None = "100") -> PricingContext:
    return PricingContext(
        destination_id=None,
        destination_name="Unlisted delivery location",
        quote_date=date(2026, 10, 8),
        distance_km=Decimal(distance) if distance is not None else None,
    )


def _config(**overrides: Any) -> DynamicPricingConfig:
    values: dict[str, Any] = {
        "version_id": "cfg1",
        "version_label": "October rate",
        "base_rate_per_km": Decimal("50"),
        "fuel_adjustment_percent": Decimal("10"),
    }
    values.update(overrides)
    return DynamicPricingConfig(**values)


def test_the_effective_rate_is_the_base_rate_adjusted_for_fuel() -> None:
    outcome = engine.price_by_distance(_context(), _config())

    assert outcome.is_priced and outcome.breakdown is not None
    breakdown = outcome.breakdown
    # 100 km x (50 + 10%) = 100 x 55.
    assert breakdown.total == Decimal("5500.00")
    assert breakdown.base_price == Decimal("5000.00")
    assert [item.kind for item in breakdown.adjustments] == [AdjustmentKind.FUEL]
    assert breakdown.adjustments[0].amount == Decimal("500.00")


def test_every_input_of_the_calculation_is_recorded_for_audit() -> None:
    outcome = engine.price_by_distance(_context("12.5"), _config())

    assert outcome.breakdown is not None
    details = outcome.breakdown.pricing_details
    assert details["distanceKm"] == "12.50"
    assert details["baseRatePerKm"] == "50.00"
    assert details["fuelAdjustmentPercent"] == "10"
    assert details["effectiveRatePerKm"] == "55.00"
    assert details["configLabel"] == "October rate"
    # base x distance, adjusted for fuel: 12.5 x 55 = 687.50.
    assert details["calculatedAmount"] == "687.50"


def test_a_minimum_charge_floors_a_short_delivery() -> None:
    outcome = engine.price_by_distance(_context("1"), _config(min_charge=Decimal("300")))

    assert outcome.breakdown is not None
    assert outcome.breakdown.total == Decimal("300.00")
    floored = outcome.breakdown.adjustments[-1]
    assert floored.kind is AdjustmentKind.MINIMUM
    # 1 km x 55 would be 55; the floor adds exactly the difference, never the whole charge.
    assert floored.amount == Decimal("245.00")
    assert outcome.breakdown.pricing_details["minCharge"] == "300.00"


def test_no_configuration_refuses_instead_of_defaulting_to_a_rate() -> None:
    outcome = engine.price_by_distance(_context(), None)

    assert not outcome.is_priced
    assert outcome.reason == engine.Reason.DYNAMIC_PRICING_UNAVAILABLE
    assert outcome.breakdown is None


def test_no_road_distance_refuses_instead_of_guessing_one() -> None:
    outcome = engine.price_by_distance(_context(distance=None), _config())

    assert not outcome.is_priced
    assert outcome.reason == engine.Reason.DISTANCE_REQUIRED


def test_a_negative_fuel_adjustment_lowers_the_rate() -> None:
    outcome = engine.price_by_distance(
        _context("10"), _config(base_rate_per_km=Decimal("100"), fuel_adjustment_percent=Decimal("-5"))
    )

    assert outcome.breakdown is not None
    assert outcome.breakdown.pricing_details["effectiveRatePerKm"] == "95.00"
    assert outcome.breakdown.total == Decimal("950.00")


def test_a_distance_quote_is_labelled_as_model_b() -> None:
    outcome = engine.price_by_distance(_context(), _config())

    assert outcome.breakdown is not None
    assert outcome.breakdown.pricing_model.value == "distance_based"
    assert outcome.breakdown.version_id == "cfg1"


# ------------------------------------------------------------------ admin configuration


async def _activate(client: AsyncClient, *, label: str = "October rate", base: str = "50", fuel: str = "10") -> str:
    created = await client.post(
        "/api/v1/admin/dynamic-pricing",
        json={"label": label, "baseRatePerKm": base, "fuelAdjustmentPercent": fuel},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    activated = await client.post(f"/api/v1/admin/dynamic-pricing/{version_id}/activate")
    assert activated.status_code == 200, activated.text
    return version_id


async def test_a_configuration_starts_as_a_draft_and_changes_nothing(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/admin/dynamic-pricing",
        json={"label": "October rate", "baseRatePerKm": "50", "fuelAdjustmentPercent": "10"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    # The effective rate is what a customer would actually pay per kilometre.
    assert Decimal(body["effectiveRatePerKm"]) == Decimal("55.00")
    active = await client.get("/api/v1/admin/dynamic-pricing/active")
    assert active.json() is None, "a draft must not price anything"


async def test_activating_a_new_rate_retires_the_previous_one(client: AsyncClient) -> None:
    await _activate(client, label="October rate")
    await _activate(client, label="November rate", base="60", fuel="0")

    active = await client.get("/api/v1/admin/dynamic-pricing/active")
    assert active.json()["label"] == "November rate"
    listed = (await client.get("/api/v1/admin/dynamic-pricing")).json()
    statuses = {item["label"]: item["status"] for item in listed}
    assert statuses == {"October rate": "retired", "November rate": "active"}


async def test_an_active_configuration_cannot_be_edited(client: AsyncClient) -> None:
    version_id = await _activate(client)

    patched = await client.patch(
        f"/api/v1/admin/dynamic-pricing/{version_id}", json={"baseRatePerKm": "999"}
    )

    assert patched.status_code == 422
    assert "create a new one" in patched.json()["message"].lower()
    active = await client.get("/api/v1/admin/dynamic-pricing/active")
    assert Decimal(active.json()["baseRatePerKm"]) == Decimal("50")


async def test_retiring_switches_distance_pricing_off(client: AsyncClient) -> None:
    version_id = await _activate(client)

    retired = await client.post(f"/api/v1/admin/dynamic-pricing/{version_id}/retire")
    assert retired.status_code == 200, retired.text
    assert (await client.get("/api/v1/admin/dynamic-pricing/active")).json() is None

    # A draft was never active, so "retire" is a category error, not a silent no-op.
    draft = await client.post(
        "/api/v1/admin/dynamic-pricing", json={"label": "Later", "baseRatePerKm": "70"}
    )
    refused = await client.post(f"/api/v1/admin/dynamic-pricing/{draft.json()['id']}/retire")
    assert refused.status_code == 422


async def test_preview_goes_through_the_real_engine(client: AsyncClient) -> None:
    await _activate(client)

    preview = await client.post("/api/v1/admin/dynamic-pricing/preview", json={"distanceKm": "100"})

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["priced"] is True
    assert Decimal(body["total"]) == Decimal("5500.00")
    assert Decimal(body["effectiveRatePerKm"]) == Decimal("55.00")
    assert body["configLabel"] == "October rate"
    assert [item["kind"] for item in body["adjustments"]] == ["fuel"]


async def test_preview_can_try_an_unsaved_rate(client: AsyncClient) -> None:
    await _activate(client, fuel="0")

    preview = await client.post(
        "/api/v1/admin/dynamic-pricing/preview",
        json={"distanceKm": "10", "baseRatePerKm": "80"},
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert Decimal(body["total"]) == Decimal("800.00")
    # Nothing was saved, and the label says so rather than borrowing the stored one.
    assert body["configLabel"] == "October rate (preview)"
    active = await client.get("/api/v1/admin/dynamic-pricing/active")
    assert Decimal(active.json()["baseRatePerKm"]) == Decimal("50")


async def test_preview_without_any_configuration_says_so(client: AsyncClient) -> None:
    preview = await client.post("/api/v1/admin/dynamic-pricing/preview", json={"distanceKm": "10"})

    assert preview.status_code == 422
    assert preview.json()["code"] == "VALIDATION"


async def test_anonymous_callers_cannot_read_or_write_distance_pricing(
    anon_client: AsyncClient,
) -> None:
    read = await anon_client.get("/api/v1/admin/dynamic-pricing")
    write = await anon_client.post(
        "/api/v1/admin/dynamic-pricing", json={"label": "Nope", "baseRatePerKm": "10"}
    )

    assert read.status_code == 401
    assert write.status_code == 401


async def test_a_viewer_reads_but_never_writes(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/admin/users",
        json={"email": "viewer@rims.test", "fullName": "Viewer", "password": PASSWORD, "role": "viewer"},
    )
    assert created.status_code == 201, created.text

    async with _app_client() as http:
        login = await http.post(
            "/api/v1/auth/login", json={"email": "viewer@rims.test", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        assert (await http.get("/api/v1/admin/dynamic-pricing")).status_code == 200

        write = await http.post(
            "/api/v1/admin/dynamic-pricing", json={"label": "Viewer rate", "baseRatePerKm": "10"}
        )
        assert write.status_code == 403


async def test_an_editor_configures_but_only_an_admin_activates(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/admin/users",
        json={"email": "editor@rims.test", "fullName": "Editor", "password": PASSWORD, "role": "editor"},
    )
    assert created.status_code == 201, created.text

    async with _app_client() as http:
        login = await http.post(
            "/api/v1/auth/login", json={"email": "editor@rims.test", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text

        made = await http.post(
            "/api/v1/admin/dynamic-pricing",
            json={"label": "Editor rate", "baseRatePerKm": "40"},
        )
        assert made.status_code == 201, made.text

        activated = await http.post(f"/api/v1/admin/dynamic-pricing/{made.json()['id']}/activate")
        assert activated.status_code == 403


# ------------------------------------------------------------------ end-to-end quotes


def _app_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _configure_priced_nakuru(client: AsyncClient) -> str:
    """RIMs' official price list: Nakuru costs 1,500 KES, and nothing else is listed."""
    created = await client.post(
        "/api/v1/admin/destinations",
        json={"name": "Nakuru", "code": "NAK", "aliases": ["Nakuru Town"]},
    )
    assert created.status_code == 201, created.text
    destination_id = created.json()["id"]

    version = await client.post(
        "/api/v1/admin/pricing-versions",
        json={"label": "2026-01", "effectiveFrom": "2026-01-01"},
    )
    assert version.status_code == 201, version.text
    rule = await client.post(
        "/api/v1/admin/pricing-rules",
        json={"destinationId": destination_id, "basePrice": "1500.00", "versionId": version.json()["id"]},
    )
    assert rule.status_code == 201, rule.text
    await client.post(
        f"/api/v1/admin/pricing-versions/{version.json()['id']}/confirm-validation", json={}
    )
    activated = await client.post(f"/api/v1/admin/pricing-versions/{version.json()['id']}/activate")
    assert activated.status_code == 200, activated.text
    return destination_id


async def _run_pipeline(client: AsyncClient, *, label: str) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/public/quotes",
        json={
            "position": {"lat": DISPATCH_LAT, "lng": DISPATCH_LNG},
            "label": label,
            "resolved": True,
        },
    )
    assert created.status_code == 202, created.text
    final = await client.get(f"/api/v1/public/quotes/{created.json()['id']}")
    assert final.status_code == 200, final.text
    return final.json()


async def test_a_location_outside_the_price_list_is_priced_from_its_road_distance(
    client: AsyncClient,
) -> None:
    await _configure_priced_nakuru(client)
    await _activate(client)

    # "Naivasha Town" matches no configured destination, so model A has nothing to say.
    body = await _run_pipeline(client, label="Naivasha Town")

    assert body["status"] == "completed", body
    assert body["destination"] is None
    assert body["pricingModel"] == "distance_based"
    # 100 km (the stub provider) x 55/km (50 + 10% fuel).
    assert Decimal(str(body["fee"]["amount"])) == Decimal("5500.00")
    assert Decimal(str(body["distanceKm"])) == Decimal("100.00")
    explanation = body["pricingExplanation"]
    assert "100.00 km" in explanation
    assert "55.00/km" in explanation
    assert "fuel adjustment" in explanation


async def test_an_official_price_is_never_replaced_by_the_distance_rate(
    client: AsyncClient,
) -> None:
    await _configure_priced_nakuru(client)
    await _activate(client, base="50", fuel="10")

    # "Nakuru" is on RIMs' price list, so the fixed price wins even though the dynamic rate
    # exists and would have produced a different number.
    body = await _run_pipeline(client, label="Nakuru")

    assert body["status"] == "completed", body
    assert body["pricingModel"] == "fixed_destination"
    assert Decimal(str(body["fee"]["amount"])) == Decimal("1500.00")
    assert "Official RIMs price" in body["pricingExplanation"]
    assert "Nakuru" in body["pricingExplanation"]


async def test_without_a_rate_an_unlisted_location_stays_unpriced(
    client: AsyncClient,
) -> None:
    await _configure_priced_nakuru(client)

    body = await _run_pipeline(client, label="Naivasha Town")

    assert body["status"] == "needs_review", body
    assert body["failure"]["code"] == "DESTINATION_UNSUPPORTED"
    assert body["fee"] is None
    assert body["pricingModel"] is None


async def test_retiring_the_rate_stops_pricing_new_unlisted_locations(
    client: AsyncClient,
) -> None:
    await _configure_priced_nakuru(client)
    version_id = await _activate(client)
    await client.post(f"/api/v1/admin/dynamic-pricing/{version_id}/retire")

    body = await _run_pipeline(client, label="Naivasha Town")

    assert body["status"] == "needs_review", body
    assert body["failure"]["code"] == "DESTINATION_UNSUPPORTED"


async def test_the_admin_breakdown_shows_the_calculation_the_customer_cannot_see(
    client: AsyncClient,
) -> None:
    await _configure_priced_nakuru(client)
    await _activate(client)
    body = await _run_pipeline(client, label="Naivasha Town")

    detail = (await client.get(f"/api/v1/admin/quotes/{body['id']}")).json()
    breakdown = detail["breakdown"]
    assert breakdown["pricingModel"] == "distance_based"
    assert breakdown["pricingVersion"] == "October rate"
    details = breakdown["pricingDetails"]
    assert Decimal(details["distanceKm"]) == Decimal("100.00")
    assert Decimal(details["baseRatePerKm"]) == Decimal("50.00")
    assert Decimal(details["effectiveRatePerKm"]) == Decimal("55.00")
    assert Decimal(details["calculatedAmount"]) == Decimal("5500.00")
    # The customer still gets no breakdown rows - only the explanation.
    assert "breakdown" not in (await client.get(f"/api/v1/public/quotes/{body['id']}")).json()


async def test_a_dynamic_quote_never_writes_the_fixed_version_foreign_key(
    client: AsyncClient, session: AsyncSession
) -> None:
    """``quotes.pricing_version_id`` points at the fixed price list; a distance-based quote
    has no fixed version, and storing a dynamic id there would break that reference."""
    await _configure_priced_nakuru(client)
    await _activate(client)
    body = await _run_pipeline(client, label="Naivasha Town")

    await session.rollback()
    stored = await session.execute(
        text("select pricing_version_id, pricing_model from quotes where id = :id"),
        {"id": body["id"]},
    )
    pricing_version_id, pricing_model = stored.one()
    assert pricing_version_id is None
    assert pricing_model == "distance_based"


# ------------------------------------------------------------------ bootstrap seeding


async def test_a_fresh_install_seeds_an_active_default_distance_rate(
    session: AsyncSession,
) -> None:
    """An untouched install charges 150 KES/km for unlisted locations without any manual setup."""
    from app.services.bootstrap import DEFAULT_DISTANCE_LABEL, ensure_default_distance_pricing
    from app.services.pricing.repository import load_active_dynamic_pricing

    row = await ensure_default_distance_pricing(session)

    assert row is not None
    assert row.label == DEFAULT_DISTANCE_LABEL
    assert row.status is PricingVersionStatus.ACTIVE
    assert row.base_rate_per_km == Decimal("150")
    assert row.currency == "KES"
    active = await load_active_dynamic_pricing(session)
    assert active is not None
    assert active.base_rate_per_km == Decimal("150")


async def test_the_seed_never_overrides_an_existing_configuration(
    session: AsyncSession,
) -> None:
    """Once any rate exists - even a retired one RIMs switched off - the seed stays out of the way."""
    from app.services.bootstrap import ensure_default_distance_pricing

    session.add(
        DynamicPricingVersion(
            label="RIMs own rate",
            status=PricingVersionStatus.RETIRED,
            base_rate_per_km=Decimal("80"),
        )
    )
    await session.commit()

    row = await ensure_default_distance_pricing(session)

    assert row is None
    count = int(await session.scalar(select(func.count(DynamicPricingVersion.id))) or 0)
    assert count == 1


async def test_the_seed_can_be_switched_off(session: AsyncSession) -> None:
    from app.services.bootstrap import ensure_default_distance_pricing

    settings = get_settings().model_copy(update={"auto_seed_distance_pricing": False})
    row = await ensure_default_distance_pricing(session, settings)

    assert row is None
    count = int(await session.scalar(select(func.count(DynamicPricingVersion.id))) or 0)
    assert count == 0


async def test_a_seeded_rate_prices_an_unlisted_location_end_to_end(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The whole point: a place outside the price list is quoted, not refused, out of the box."""
    from app.services.bootstrap import ensure_default_distance_pricing

    await _configure_priced_nakuru(client)
    await ensure_default_distance_pricing(session)
    await session.commit()

    body = await _run_pipeline(client, label="Naivasha Town")

    assert body["status"] == "completed", body
    assert body["destination"] is None
    assert body["pricingModel"] == "distance_based"
    # 100 km (the stub provider) x 150 KES/km (the seeded rate).
    assert Decimal(str(body["fee"]["amount"])) == Decimal("15000.00")


async def test_the_customer_sees_the_arithmetic_but_not_the_working(
    client: AsyncClient,
) -> None:
    """The explanation is the transparency; the calculation rows stay staff-only."""
    await _configure_priced_nakuru(client)
    await _activate(client)
    body = await _run_pipeline(client, label="Naivasha Town")

    assert Decimal(str(body["fee"]["amount"])) == Decimal("5500.00")
    assert "calculations" not in body
    assert "breakdown" not in body
    assert body["pricingExplanation"].startswith("Road distance 100.00 km")

    detail = (await client.get(f"/api/v1/admin/quotes/{body['id']}")).json()
    calculation = detail["calculations"][0]
    assert calculation["pricingModel"] == "distance_based"
    assert Decimal(calculation["total"]["amount"]) == Decimal("5500.00")
    assert calculation["pricingDetails"]["distanceKm"] == "100.00"
