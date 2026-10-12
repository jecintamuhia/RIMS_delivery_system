"""CSV price-list import tests.

This is the only way a price enters the system, so these tests care about the promises the service
makes in its own docstring:

* a dry run writes nothing and reports exactly what an apply would create;
* an apply creates a ``draft`` version and never activates it - activation is a separate decision;
* unknown destinations, zones, road types and vehicles are *created*, never dropped, and the
  created records are reported back;
* every row that cannot be understood becomes a reported problem instead of aborting the file, so
  one typo does not cost the operator the other 4,999 rows;
* nothing is invented. No seed prices, no fallback destination, no default currency guess.

Rows are built with ``csv.writer`` from a dict of column names rather than by hand, because a
mis-counted comma silently shifts every value to the wrong column and produces a test that passes
for the wrong reason.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.errors import AppError, ErrorCode
from app.models import (
    DeliveryZone,
    Destination,
    DestinationAlias,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    RoadType,
    VehicleCategory,
)
from app.services.pricing.import_csv import import_pricing_csv

COLUMNS = (
    "destination_name",
    "destination_code",
    "destination_aliases",
    "zone_name",
    "zone_code",
    "base_price",
    "road_adjustment_type",
    "road_adjustment_value",
    "vehicle_adjustment_type",
    "vehicle_adjustment_value",
    "road_type_name",
    "vehicle_name",
    "min_charge",
    "priority",
    "effective_from",
    "effective_to",
    "notes",
)


async def test_admin_can_list_only_available_price_list_filenames(client: Any) -> None:
    response = await client.get("/api/v1/admin/pricing-import/files")

    assert response.status_code == 200
    files = response.json()
    assert "rims_transport_costs.csv" in files
    assert all(Path(name).name == name and name.endswith(".csv") for name in files)


async def test_price_list_filenames_require_staff_session(anon_client: Any) -> None:
    response = await anon_client.get("/api/v1/admin/pricing-import/files")

    assert response.status_code == 401


def row(**overrides: str) -> str:
    """One CSV line. Only the named columns are set; the rest are blank."""
    values = dict.fromkeys(COLUMNS, "")
    values.update(overrides)
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow([values[column] for column in COLUMNS])
    return buffer.getvalue()


def write_csv(
    directory: Path,
    name: str,
    rows: list[str],
    *,
    header: str | None = None,
) -> str:
    """Write a price list into the pricing data directory and return its filename."""
    header_line = header if header is not None else ",".join(COLUMNS)
    directory.joinpath(name).write_text("\n".join([header_line, *rows]) + "\n", encoding="utf-8")
    return name


@pytest.fixture
def pricing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the importer at a throwaway directory instead of the repository's data folder."""
    target = tmp_path / "pricing"
    target.mkdir()
    monkeypatch.setattr("app.services.pricing.import_csv.pricing_data_dir", lambda: target)
    return target


async def run_import(
    session: Any,
    *,
    filename: str = "prices.csv",
    label: str = "2026-01",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
    dry_run: bool = True,
    notes: str | None = None,
    actor_id: str | None = None,
) -> Any:
    return await import_pricing_csv(
        session,
        filename=filename,
        label=label,
        effective_from=effective_from,
        effective_to=effective_to,
        dry_run=dry_run,
        notes=notes,
        actor_id=actor_id,
    )


async def count(session: Any, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def only_rule(session: Any) -> PricingRule:
    """The single rule the import created. Fails loudly if there is not exactly one."""
    rules = await collected(session, PricingRule)
    assert len(rules) == 1, f"expected exactly one pricing rule, found {len(rules)}"
    return rules[0]


async def collected[ModelT](session: Any, model: type[ModelT]) -> list[ModelT]:
    return list((await session.scalars(select(model))).all())


# --------------------------------------------------------------------------- dry run


async def test_dry_run_reports_what_would_be_created_without_writing(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(
                destination_name="Nakuru",
                destination_aliases="Nakuru Town;NK Town",
                zone_name="Nakuru Zone",
                zone_code="ZNK",
                base_price="1200",
                effective_from="2026-01-01",
                notes="base",
            ),
            row(
                destination_name="Eldoret",
                zone_name="Eldoret Zone",
                zone_code="ZEL",
                base_price="1800",
                road_adjustment_type="percent",
                road_adjustment_value="10",
                effective_from="2026-01-01",
            ),
        ],
    )

    report = await run_import(session, dry_run=True)

    assert report.dry_run is True
    assert report.version_id is None
    assert report.destination_count == 2
    assert report.rule_count == 2
    assert sorted(report.created_destinations) == ["Eldoret", "Nakuru"]
    assert sorted(report.created_zones) == ["Eldoret Zone", "Nakuru Zone"]
    assert sorted(report.created_aliases) == ["NK Town", "Nakuru Town"]
    assert report.problems == []

    # Nothing at all may be written by a dry run.
    assert await count(session, PricingVersion) == 0
    assert await count(session, PricingRule) == 0
    assert await count(session, Destination) == 0
    assert await count(session, DeliveryZone) == 0
    assert await count(session, DestinationAlias) == 0


async def test_dry_run_and_apply_report_the_same_creations(
    session: Any, pricing_dir: Path
) -> None:
    """A dry run is only useful if it predicts the real thing."""
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(
                destination_name="Nakuru",
                destination_aliases="Nakuru Town",
                zone_name="Nakuru Zone",
                base_price="1200",
                effective_from="2026-01-01",
            ),
            row(
                destination_name="Kisumu",
                base_price="2500",
                road_adjustment_type="fixed",
                road_adjustment_value="500",
                vehicle_name="Van",
                min_charge="2000",
                priority="5",
                effective_from="2026-01-01",
                effective_to="2026-06-30",
            ),
        ],
    )

    dry = await run_import(session, label="dry", dry_run=True)
    applied = await run_import(session, label="apply", dry_run=False)
    await session.commit()

    assert dry.destination_count == applied.destination_count
    assert dry.rule_count == applied.rule_count
    assert sorted(dry.created_destinations) == sorted(applied.created_destinations)
    assert sorted(dry.created_aliases) == sorted(applied.created_aliases)
    assert sorted(dry.created_zones) == sorted(applied.created_zones)
    assert dry.created_vehicles == applied.created_vehicles


# --------------------------------------------------------------------------- apply


async def test_apply_creates_a_draft_version_with_the_prices_it_was_given(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru", base_price="1200.50", effective_from="2026-01-01")],
    )

    report = await run_import(session, dry_run=False, notes="RIMs January list")
    await session.commit()

    version = await session.get(PricingVersion, report.version_id)
    assert version is not None
    assert version.status is PricingVersionStatus.DRAFT, "an import must never activate a price"
    assert version.label == "2026-01"
    assert version.effective_from == date(2026, 1, 1)
    assert version.currency == "KES"
    assert version.source == "csv:prices.csv"
    assert version.notes == "RIMs January list"

    rule = await only_rule(session)
    assert rule.base_price == Decimal("1200.50"), "the price must be stored exactly as sent"
    assert rule.effective_from == date(2026, 1, 1)
    assert rule.is_active is True
    assert rule.destination_id is not None


async def test_apply_records_the_acting_admin_when_given_one(
    session: Any, pricing_dir: Path
) -> None:
    from app.models import Role, User
    from app.security import hash_password

    user = User(
        email="importer@rims.test",
        full_name="Importer",
        password_hash=hash_password("correct-horse-battery"),
        role=Role.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    write_csv(
        pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1200")]
    )

    report = await run_import(session, dry_run=False, actor_id=user.id)
    await session.commit()

    version = await session.get(PricingVersion, report.version_id)
    assert version is not None
    assert version.created_by_id == user.id


async def test_apply_attaches_the_zone_the_row_named(session: Any, pricing_dir: Path) -> None:
    """Regression: the zone was created and reported, but its id was thrown away."""
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru", zone_name="Nakuru Zone", base_price="1200")],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    destination = (await collected(session, Destination))[0]
    assert destination.zone_id is not None, "a destination created from a row must land in its zone"

    zone = await session.get(DeliveryZone, destination.zone_id)
    assert zone is not None
    assert zone.name == "Nakuru Zone"
    assert zone.code.startswith("Z")
    assert report.created_zones == ["Nakuru Zone"]


async def test_explicit_zone_code_is_used_as_given(session: Any, pricing_dir: Path) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru", zone_name="Nakuru Zone", zone_code="ZNK", base_price="1200")],
    )

    await run_import(session, dry_run=False)
    await session.commit()

    assert (await collected(session, DeliveryZone))[0].code == "ZNK"


async def test_reimport_does_not_move_a_destination_that_staff_already_zoned(
    session: Any, pricing_dir: Path
) -> None:
    """Re-running an import must not silently reclassify live reference data."""
    zone = DeliveryZone(name="Hand-set zone", code="ZHAND")
    session.add(zone)
    await session.commit()

    destination = Destination(name="Nakuru", code="nakuru", zone_id=zone.id)
    session.add(destination)
    await session.commit()

    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru", zone_name="CSV zone", base_price="1200")],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    reloaded = await session.get(Destination, destination.id)
    assert reloaded is not None
    assert reloaded.zone_id == zone.id
    assert report.created_zones == ["CSV zone"], "the zone is still created, just not applied"


async def test_unknown_road_types_and_vehicles_are_created_not_dropped(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(
                destination_name="Nakuru",
                base_price="1000",
                road_adjustment_type="percent",
                road_adjustment_value="15",
                vehicle_adjustment_type="fixed",
                vehicle_adjustment_value="750",
                road_type_name="Tarmac Road",
                vehicle_name="Cycle Rickshaw",
            )
        ],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.created_road_types == ["Tarmac Road"]
    assert report.created_vehicles == ["Cycle Rickshaw"]
    assert await count(session, RoadType) == 1
    assert await count(session, VehicleCategory) == 1

    rule = await only_rule(session)
    assert rule.road_type_id is not None
    assert rule.vehicle_id is not None
    assert rule.road_adjustment_type.value == "percent"
    assert rule.road_adjustment_value == Decimal("15.00")
    assert rule.vehicle_adjustment_value == Decimal("750.00")


async def test_aliases_are_created_and_a_clashing_alias_is_skipped(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(
                destination_name="Nakuru",
                destination_aliases="Nakuru Town;NK Town",
                base_price="1200",
            ),
            row(
                destination_name="Eldoret",
                destination_aliases="Nakuru Town",
                base_price="1800",
                notes="alias already owned by Nakuru",
            ),
        ],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    aliases = {row_.alias: str(row_.destination_id) for row_ in await collected(session, DestinationAlias)}
    assert set(aliases) == {"Nakuru Town", "NK Town"}
    assert "Nakuru Town" in report.created_aliases

    nakuru = (await session.scalars(select(Destination).where(Destination.name == "Nakuru"))).one()
    assert aliases["Nakuru Town"] == nakuru.id, "the first row must keep the alias"


async def test_alias_matching_is_case_and_spacing_insensitive(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(destination_name="Nakuru", destination_aliases="Nakuru Town", base_price="1200"),
            row(destination_name="Eldoret", destination_aliases="  nakuru   town ", base_price="1800"),
        ],
    )

    await run_import(session, dry_run=False)
    await session.commit()

    assert await count(session, DestinationAlias) == 1, "the same alias in another case is not new"


async def test_second_import_reuses_destinations_and_rules_a_new_version(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000")])

    first = await run_import(session, label="2026-01", dry_run=False)
    await session.commit()
    second = await run_import(session, label="2026-07", dry_run=False)
    await session.commit()

    assert first.version_id != second.version_id
    assert await count(session, Destination) == 1, "an existing destination must be reused"
    assert second.created_destinations == []
    assert await count(session, PricingVersion) == 2
    assert await count(session, PricingRule) == 2, "each version keeps its own copy of the price"


async def test_duplicate_label_is_rejected_rather_than_silently_replacing(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000")])
    await run_import(session, label="2026-01", dry_run=False)
    await session.commit()

    with pytest.raises(AppError) as excinfo:
        await run_import(session, label="2026-01", dry_run=False)

    assert excinfo.value.code is ErrorCode.VALIDATION
    assert "2026-01" in excinfo.value.message
    assert await count(session, PricingVersion) == 1


async def test_rollback_leaves_no_partial_import(session: Any, pricing_dir: Path) -> None:
    """The service does not commit, so a caller that rolls back keeps none of it."""
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000")])

    await run_import(session, dry_run=False)
    await session.rollback()

    assert await count(session, PricingVersion) == 0
    assert await count(session, PricingRule) == 0
    assert await count(session, Destination) == 0


async def test_duplicate_scope_in_one_file_is_reported_not_imported_twice(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(destination_name="Nakuru", base_price="1000"),
            row(destination_name="Nakuru", base_price="2000", notes="same destination twice"),
        ],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.rule_count == 1
    assert report.destination_count == 1
    assert any("duplicates an earlier row" in problem for problem in report.problems)
    assert await count(session, PricingRule) == 1


async def test_same_destination_with_different_road_types_is_not_a_duplicate(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(destination_name="Nakuru", base_price="1000"),
            row(destination_name="Nakuru", base_price="1200", road_type_name="Gravel Road"),
        ],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.problems == []
    assert report.rule_count == 2


# --------------------------------------------------------------------------- row problems


async def test_a_bad_row_is_reported_and_the_good_rows_still_import(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(destination_name="Nakuru", base_price="1000"),
            row(destination_name="Broken", base_price="not-a-number"),
            row(destination_name="Eldoret", base_price="1800"),
        ],
    )

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.rule_count == 2
    assert report.destination_count == 2
    assert len(report.problems) == 1
    assert report.problems[0].startswith("Row 3:")
    assert "base_price" in report.problems[0]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"base_price": "1000"}, None, id="valid-baseline"),
        pytest.param({"base_price": "1000.75"}, None, id="decimal-price"),
        pytest.param({"base_price": "2,500.75"}, None, id="thousands-separator"),
        pytest.param({"effective_to": "2026-01-01"}, None, id="same-day-range-is-legal"),
        pytest.param({"road_adjustment_type": "none"}, None, id="explicit-none-adjustment"),
        pytest.param({"priority": "-3"}, None, id="negative-priority-allowed"),
        pytest.param({"base_price": "-50"}, "cannot be negative", id="negative-base"),
        pytest.param({"base_price": ""}, "base_price is required", id="missing-base-price"),
        pytest.param({"destination_name": ""}, "destination_name is required", id="missing-name"),
        pytest.param({"effective_from": "2026-13-45"}, "not a date", id="impossible-date"),
        pytest.param({"effective_from": "01/02/2026"}, None, id="day-first-date-accepted"),
        pytest.param({"priority": "high"}, "priority is not a whole number", id="bad-priority"),
        pytest.param({"min_charge": "free"}, "min_charge is not a number", id="bad-min-charge"),
        pytest.param(
            {"effective_from": "2026-12-31", "effective_to": "2026-01-01"},
            "effective_to is before effective_from",
            id="inverted-dates",
        ),
        pytest.param(
            {"road_adjustment_type": "bogus", "road_adjustment_value": "10"},
            "road_adjustment_type must be one of",
            id="unknown-adjustment-type",
        ),
        pytest.param(
            {"road_adjustment_type": "percent"},
            "road_adjustment_value is required",
            id="adjustment-value-missing",
        ),
        pytest.param(
            {"road_adjustment_type": "percent", "road_adjustment_value": "-5"},
            "road_adjustment_value cannot be negative",
            id="negative-adjustment",
        ),
        pytest.param(
            {"vehicle_adjustment_type": "fixed"},
            "vehicle_adjustment_value is required",
            id="vehicle-adjustment-value-missing",
        ),
    ],
)
async def test_row_validation_messages(
    session: Any, pricing_dir: Path, overrides: dict[str, str], expected: str | None
) -> None:
    values = {"destination_name": "Nakuru", "base_price": "1000", **overrides}
    write_csv(pricing_dir, "prices.csv", [row(**values)])

    report = await run_import(session, dry_run=True)

    if expected is None:
        assert report.problems == [], f"unexpected problem: {report.problems}"
        assert report.rule_count == 1
    else:
        assert len(report.problems) == 1, report.problems
        assert expected in report.problems[0], report.problems[0]
        assert report.rule_count == 0


async def test_problems_name_the_line_the_operator_can_find(
    session: Any, pricing_dir: Path
) -> None:
    """Row numbers must match the spreadsheet, so they are reported from the first data row as 2."""
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(destination_name="Nakuru", base_price="1000"),
            row(destination_name="Eldoret", base_price="1000"),
            row(destination_name="Broken", base_price="oops"),
        ],
    )

    report = await run_import(session, dry_run=True)

    assert len(report.problems) == 1
    assert report.problems[0].startswith("Row 4:"), report.problems[0]


async def test_blank_lines_are_skipped(session: Any, pricing_dir: Path) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru", base_price="1000"), "", "   "],
    )

    report = await run_import(session, dry_run=True)

    assert report.problems == []
    assert report.rule_count == 1


async def test_file_with_only_bad_rows_reports_and_creates_nothing(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "prices.csv", [row(base_price="1000")])

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.rule_count == 0
    assert report.problems
    assert await count(session, PricingVersion) == 0
    assert await count(session, Destination) == 0


async def test_empty_file_says_so_instead_of_creating_an_empty_version(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "prices.csv", [])

    report = await run_import(session, dry_run=False)
    await session.commit()

    assert report.problems == ["The price list contains no usable rows."]
    assert report.version_id is None
    assert await count(session, PricingVersion) == 0


# --------------------------------------------------------------------------- file handling


async def test_missing_required_column_is_named_in_the_error(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "bad.csv", ["1000"], header="base_price")

    with pytest.raises(AppError) as excinfo:
        await run_import(session, filename="bad.csv", dry_run=True)

    assert excinfo.value.code is ErrorCode.VALIDATION
    assert "destination_name" in excinfo.value.message


async def test_optional_columns_may_be_absent_entirely(
    session: Any, pricing_dir: Path
) -> None:
    """A two-column file is legal: only destination_name and base_price are required."""
    write_csv(
        pricing_dir,
        "minimal.csv",
        ["Nakuru,1200"],
        header="destination_name,base_price",
    )

    report = await run_import(session, filename="minimal.csv", dry_run=False)
    await session.commit()

    assert report.problems == []
    assert report.rule_count == 1
    assert (await only_rule(session)).base_price == Decimal("1200.00")


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("../secrets.csv", id="parent-traversal"),
        pytest.param("..\\..\\windows\\system32\\drivers\\etc\\hosts.csv", id="windows-traversal"),
        pytest.param("/etc/passwd.csv", id="absolute"),
        pytest.param("nested/deeper.csv", id="subdirectory"),
    ],
)
async def test_paths_outside_the_pricing_directory_are_refused(
    session: Any, pricing_dir: Path, filename: str
) -> None:
    with pytest.raises(AppError) as excinfo:
        await run_import(session, filename=filename, dry_run=True)

    assert excinfo.value.code is ErrorCode.VALIDATION


async def test_non_csv_extension_is_refused(session: Any, pricing_dir: Path) -> None:
    (pricing_dir / "prices.xlsx").write_text("nope", encoding="utf-8")

    with pytest.raises(AppError) as excinfo:
        await run_import(session, filename="prices.xlsx", dry_run=True)

    assert ".csv" in excinfo.value.message


async def test_missing_file_error_lists_what_is_available(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "available.csv", [row(destination_name="Nakuru", base_price="1000")])

    with pytest.raises(AppError) as excinfo:
        await run_import(session, filename="typo.csv", dry_run=True)

    assert "typo.csv" in excinfo.value.message
    assert "available.csv" in excinfo.value.message


async def test_byte_order_mark_is_tolerated(session: Any, pricing_dir: Path) -> None:
    """Excel exports a BOM; the first destination name must not come out as ``\\ufeffNakuru``."""
    (pricing_dir / "excel.csv").write_text(
        "﻿" + ",".join(COLUMNS) + "\n" + row(destination_name="Nakuru", base_price="1000") + "\n",
        encoding="utf-8",
    )

    report = await run_import(session, filename="excel.csv", dry_run=False)
    await session.commit()

    assert report.problems == []
    assert (await collected(session, Destination))[0].name == "Nakuru"


async def test_money_is_stored_to_two_decimal_places(session: Any, pricing_dir: Path) -> None:
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000.5")])

    await run_import(session, dry_run=False)
    await session.commit()

    assert str((await only_rule(session)).base_price) == "1000.50"


async def test_blank_min_charge_stays_null_rather_than_becoming_zero(
    session: Any, pricing_dir: Path
) -> None:
    """Zero and "not set" are different decisions: only the column says which was meant."""
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000")])

    await run_import(session, dry_run=False)
    await session.commit()

    assert (await only_rule(session)).min_charge is None


async def test_explicit_zero_min_charge_is_kept_as_zero(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000", min_charge="0")]
    )

    await run_import(session, dry_run=False)
    await session.commit()

    assert (await only_rule(session)).min_charge == Decimal("0.00")


async def test_row_effective_to_wins_over_the_version_window(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [
            row(
                destination_name="Nakuru",
                base_price="1000",
                effective_from="2026-02-01",
                effective_to="2026-03-31",
            )
        ],
    )

    await run_import(
        session,
        dry_run=False,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    await session.commit()

    version = (await collected(session, PricingVersion))[0]
    rule = await only_rule(session)
    assert version.effective_from == date(2026, 1, 1)
    assert version.effective_to == date(2026, 12, 31)
    assert rule.effective_from == date(2026, 2, 1), "the row's own date must win"
    assert rule.effective_to == date(2026, 3, 31)


async def test_blank_row_effective_from_falls_back_to_the_version_date(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(pricing_dir, "prices.csv", [row(destination_name="Nakuru", base_price="1000")])

    await run_import(session, dry_run=False, effective_from=date(2026, 5, 1))
    await session.commit()

    assert (await only_rule(session)).effective_from == date(2026, 5, 1)


async def test_destination_code_is_used_as_the_stable_identifier(
    session: Any, pricing_dir: Path
) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru Town", destination_code="NKR", base_price="1000")],
    )

    await run_import(session, dry_run=False)
    await session.commit()

    assert (await collected(session, Destination))[0].code == "NKR"


async def test_a_code_generated_from_the_name_is_a_slug(session: Any, pricing_dir: Path) -> None:
    write_csv(
        pricing_dir,
        "prices.csv",
        [row(destination_name="Nakuru Town Centre", base_price="1000")],
    )

    await run_import(session, dry_run=False)
    await session.commit()

    assert (await collected(session, Destination))[0].code == "NAKURUTOWNCENTRE"
