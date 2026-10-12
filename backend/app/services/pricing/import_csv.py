"""CSV price-list import.

RIMs' prices arrive as a spreadsheet export, so this is the only route by which a price enters
the system. It is built around three decisions:

* **The file is on disk, chosen by filename.** The admin API never accepts an upload body, so a
  multi-megabyte file is never held in memory or passed through a request. Files placed in
  ``data/pricing`` are validated by name.
* **Dry run first, by default.** ``dry_run=True`` reports exactly what would be created and
  every row that could not be understood, and writes nothing. Applying the import is a separate,
  explicit call.
* **Unknown references are created, not guessed.** A destination, zone, road type or vehicle
  mentioned in the file but missing from the database is *created* from that row - so the price
  RIMs actually sent is never dropped - and the creation is reported back.

The import creates a new ``PricingVersion`` in ``draft`` status. Activating it is a separate
deliberate step (see :mod:`app.api.admin.pricing`).
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, overload

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ErrorCode
from app.models import (
    AdjustmentType,
    DeliveryZone,
    Destination,
    DestinationAlias,
    PricingRule,
    PricingVersion,
    PricingVersionStatus,
    RoadType,
    VehicleCategory,
    build_scope_key,
)
from app.services.geo import normalise_place_name

logger = logging.getLogger("app.services.pricing.import_csv")

REQUIRED_COLUMNS = ("destination_name", "base_price")

OPTIONAL_COLUMNS = (
    "destination_code",
    "destination_aliases",
    "zone_name",
    "zone_code",
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

MAX_ROWS = 5_000
MAX_FILE_BYTES = 8 * 1024 * 1024

_SLUG = re.compile(r"[^A-Za-z0-9]+")


def pricing_data_dir() -> Path:
    """``backend/data/pricing``.

    ``import_csv.py`` lives at ``backend/app/services/pricing/import_csv.py``, so four levels up
    is the ``backend`` root. Resolved relative to this file rather than the working directory so
    the import works no matter where the process was started from.
    """
    return Path(__file__).resolve().parents[3] / "data" / "pricing"


@dataclass
class ParsedRow:
    line: int
    destination_name: str
    destination_code: str | None
    aliases: list[str]
    zone_name: str | None
    zone_code: str | None
    base_price: Decimal
    road_adjustment_type: AdjustmentType
    road_adjustment_value: Decimal | None
    vehicle_adjustment_type: AdjustmentType
    vehicle_adjustment_value: Decimal | None
    road_type_name: str | None
    vehicle_name: str | None
    min_charge: Decimal | None
    priority: int
    effective_from: date | None
    effective_to: date | None
    notes: str | None


@dataclass
class ImportReport:
    """What an import did, or would do. Mapped to ``ImportReport`` by the router.

    Defined here rather than imported from ``app.api`` so the service layer never depends on the
    HTTP layer.
    """

    dry_run: bool
    label: str
    version_id: str | None = None
    destination_count: int = 0
    rule_count: int = 0
    created_destinations: list[str] = field(default_factory=list)
    created_aliases: list[str] = field(default_factory=list)
    created_zones: list[str] = field(default_factory=list)
    created_road_types: list[str] = field(default_factory=list)
    created_vehicles: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class ParsedFile:
    rows: list[ParsedRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def resolve_csv_path(filename: str) -> Path:
    """Resolve a filename inside the pricing data directory, refusing any path escape."""
    candidate = (pricing_data_dir() / filename).resolve()
    root = pricing_data_dir().resolve()
    if not str(candidate).startswith(str(root)):
        # Defends against "..\\..\\etc\\passwd" being used to read arbitrary files.
        raise AppError(ErrorCode.VALIDATION, "The file name must be inside the pricing data directory.")
    if candidate.suffix.lower() != ".csv":
        raise AppError(ErrorCode.VALIDATION, "The price list must be a .csv file.")
    if not candidate.is_file():
        available = sorted(p.name for p in root.glob("*.csv")) if root.is_dir() else []
        raise AppError(
            ErrorCode.VALIDATION,
            f"No price list named “{filename}” is available on the server."
            + (f" Available: {', '.join(available)}." if available else ""),
            details={"filename": filename, "available": available},
        )
    if candidate.stat().st_size > MAX_FILE_BYTES:
        raise AppError(
            ErrorCode.VALIDATION,
            f"The price list is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. Split it and import in parts.",
        )
    return candidate


def parse_csv(path: Path, *, default_effective_from: date) -> ParsedFile:
    """Read and validate the file. Every problem is collected rather than raised on first error."""
    result = ParsedFile()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {name.strip() for name in (reader.fieldnames or []) if name}
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise AppError(
                ErrorCode.VALIDATION,
                f"The price list is missing required column(s): {', '.join(missing)}.",
                details={"missing": missing, "found": sorted(headers)},
            )

        for index, raw in enumerate(reader, start=2):
            if index > MAX_ROWS + 1:
                result.problems.append(f"Stopped after {MAX_ROWS} rows; split the file and import the rest separately.")
                break
            if not any((value or "").strip() for value in raw.values()):
                continue  # blank line
            try:
                result.rows.append(_parse_row(raw, index, default_effective_from))
            except AppError as exc:
                result.problems.append(f"Row {index}: {exc.message}")
    return result


def _parse_row(raw: dict[str, str | None], line: int, default_effective_from: date) -> ParsedRow:
    values = {key: (value or "").strip() for key, value in raw.items() if key}

    name = values.get("destination_name", "")
    if not name:
        raise AppError(ErrorCode.VALIDATION, "destination_name is required.")

    effective_from = _optional_date(values.get("effective_from"), default_effective_from)
    effective_to = _optional_date(values.get("effective_to"), None)
    if effective_to and effective_to < effective_from:
        raise AppError(ErrorCode.VALIDATION, "effective_to is before effective_from.")

    road_type, road_value = _adjustment(values, "road")
    vehicle_type, vehicle_value = _adjustment(values, "vehicle")

    return ParsedRow(
        line=line,
        destination_name=name,
        destination_code=values.get("destination_code") or None,
        aliases=_split_aliases(values.get("destination_aliases", "")),
        zone_name=values.get("zone_name") or None,
        zone_code=values.get("zone_code") or None,
        base_price=_decimal(values.get("base_price"), "base_price", required=True),
        road_adjustment_type=road_type,
        road_adjustment_value=road_value,
        vehicle_adjustment_type=vehicle_type,
        vehicle_adjustment_value=vehicle_value,
        road_type_name=values.get("road_type_name") or None,
        vehicle_name=values.get("vehicle_name") or None,
        min_charge=_decimal(values.get("min_charge"), "min_charge"),
        priority=_integer(values.get("priority"), "priority", default=0),
        effective_from=effective_from,
        effective_to=effective_to,
        notes=values.get("notes") or None,
    )


def _adjustment(values: dict[str, str], prefix: str) -> tuple[AdjustmentType, Decimal | None]:
    """Parse one adjustment column pair, enforcing "value required unless type is none"."""
    type_key = f"{prefix}_adjustment_type".strip("_")
    value_key = f"{prefix}_adjustment_value".strip("_")
    raw_type = (values.get(type_key) or "none").strip().casefold()
    raw_value = values.get(value_key) or ""
    try:
        adjustment_type = AdjustmentType(raw_type)
    except ValueError as exc:
        raise AppError(
            ErrorCode.VALIDATION,
            f"{type_key} must be one of none, fixed, percent (got “{raw_type}”).",
        ) from exc
    if adjustment_type is AdjustmentType.NONE:
        return adjustment_type, None
    value = _decimal(raw_value, value_key, required=True)
    if value < 0:
        raise AppError(ErrorCode.VALIDATION, f"{value_key} cannot be negative.")
    return adjustment_type, value


@overload
def _decimal(raw: str | None, field_name: str, *, required: Literal[True]) -> Decimal: ...


@overload
def _decimal(raw: str | None, field_name: str, *, required: bool = False) -> Decimal | None: ...


def _decimal(raw: str | None, field_name: str, *, required: bool = False) -> Decimal | None:
    """Parse a money amount. ``required=True`` always yields a Decimal or raises, so callers that
    supply a required column get a non-optional type and need no further narrowing."""
    text = (raw or "").strip().replace(",", "")
    if not text:
        if required:
            raise AppError(ErrorCode.VALIDATION, f"{field_name} is required.")
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise AppError(ErrorCode.VALIDATION, f"{field_name} is not a number (got “{text}”).") from exc
    if value < 0:
        raise AppError(ErrorCode.VALIDATION, f"{field_name} cannot be negative.")
    return value.quantize(Decimal("0.01"))


def _integer(raw: str | None, field_name: str, *, default: int = 0) -> int:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION, f"{field_name} is not a whole number (got “{text}”).") from exc


@overload
def _optional_date(raw: str | None, default: date) -> date: ...


@overload
def _optional_date(raw: str | None, default: None) -> date | None: ...


def _optional_date(raw: str | None, default: date | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return default
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise AppError(ErrorCode.VALIDATION, f"“{text}” is not a date. Use YYYY-MM-DD.")


def _split_aliases(raw: str) -> list[str]:
    parts = re.split(r"[;|]", raw or "")
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        alias = part.strip()
        if alias and normalise_place_name(alias) not in seen:
            seen.add(normalise_place_name(alias))
            out.append(alias)
    return out


def slug_code(value: str, prefix: str = "") -> str:
    slug = _SLUG.sub("", value).upper()[:16]
    return f"{prefix}{slug}" if prefix else slug


async def import_pricing_csv(
    session: AsyncSession,
    *,
    filename: str,
    label: str,
    effective_from: date,
    effective_to: date | None,
    dry_run: bool,
    notes: str | None = None,
    actor_id: str | None = None,
) -> ImportReport:
    """Validate, and optionally apply, a price list. See the module docstring for the guarantees.

    The caller commits. A dry run never writes and needs no commit.
    """
    path = resolve_csv_path(filename)
    existing_version = await session.scalar(select(PricingVersion).where(PricingVersion.label == label))
    if existing_version is not None:
        raise AppError(
            ErrorCode.VALIDATION,
            f"A pricing version labelled “{label}” already exists. Use a new label for a new price list.",
            details={"label": label},
        )

    parsed = parse_csv(path, default_effective_from=effective_from)
    problems = list(parsed.problems)
    report = ImportReport(dry_run=dry_run, label=label)

    if not parsed.rows:
        report.problems = problems or ["The price list contains no usable rows."]
        return report

    version: PricingVersion | None = None
    if not dry_run:
        version = PricingVersion(
            label=label,
            status=PricingVersionStatus.DRAFT,
            effective_from=effective_from,
            effective_to=effective_to,
            currency="KES",
            notes=notes,
            source=f"csv:{path.name}",
            created_by_id=actor_id,
        )
        session.add(version)
        await session.flush()

    # Every alias already in the database, normalised. Loaded once: uniqueness has to hold across
    # the whole file and against existing data, not just within one row.
    claimed_aliases = {
        normalise_place_name(alias)
        for alias in (await session.scalars(select(DestinationAlias.alias))).all()
    }

    seen_scopes: set[str] = set()
    destination_ids: set[str] = set()
    for row in parsed.rows:
        try:
            destination_id = await _ensure_destination(
                session, row, report, dry_run=dry_run, claimed_aliases=claimed_aliases
            )
            destination_ids.add(destination_id)
            # The zone has to be attached explicitly: _ensure_destination ran before the zone
            # existed, so a destination created from this row would otherwise have no zone at all.
            zone_id = await _ensure_zone(session, row, report, dry_run=dry_run)
            if zone_id is not None:
                await _attach_zone(session, destination_id, zone_id)
            road_type_id = await _ensure_road_type(session, row, report, dry_run=dry_run)
            vehicle_id = await _ensure_vehicle(session, row, report, dry_run=dry_run)

            scope_key = build_scope_key(destination_id, road_type_id, vehicle_id)
            if scope_key in seen_scopes:
                problems.append(
                    f"Row {row.line}: duplicates an earlier row with the same destination, "
                    "road type and vehicle."
                )
                continue
            seen_scopes.add(scope_key)

            if version is not None:
                session.add(
                    PricingRule(
                        version_id=version.id,
                        destination_id=destination_id,
                        road_type_id=road_type_id,
                        vehicle_id=vehicle_id,
                        scope_key=scope_key,
                        label=f"{row.destination_name} base price",
                        base_price=row.base_price,
                        adjustment_type=AdjustmentType.NONE,
                        adjustment_value=None,
                        road_adjustment_type=row.road_adjustment_type,
                        road_adjustment_value=row.road_adjustment_value,
                        vehicle_adjustment_type=row.vehicle_adjustment_type,
                        vehicle_adjustment_value=row.vehicle_adjustment_value,
                        min_charge=row.min_charge,
                        priority=row.priority,
                        effective_from=row.effective_from or effective_from,
                        effective_to=row.effective_to,
                        is_active=True,
                        notes=row.notes,
                    )
                )
            report.rule_count += 1
        except AppError as exc:
            problems.append(f"Row {row.line}: {exc.message}")

    report.problems = problems
    report.destination_count = len(destination_ids)
    if version is not None:
        report.version_id = version.id
        await session.flush()
    return report


async def _ensure_destination(
    session: AsyncSession,
    row: ParsedRow,
    report: ImportReport,
    *,
    dry_run: bool,
    claimed_aliases: set[str],
) -> str:
    """Find the destination by name or code, else create it. Returns its id.

    During a dry run a synthetic id is returned for a not-yet-existing destination so that scope
    de-duplication still behaves the same as it will on a real import.
    """
    code = row.destination_code or slug_code(row.destination_name)
    existing = (
        await session.execute(
            select(Destination.id, Destination.name).where(
                or_(Destination.name.ilike(row.destination_name), Destination.code == code)
            )
        )
    ).first()

    if existing is not None:
        destination_id = str(existing[0])
        if row.aliases:
            await _add_aliases(
                session,
                destination_id,
                row.aliases,
                report,
                dry_run=dry_run,
                taken=claimed_aliases,
            )
        return destination_id

    if dry_run:
        report.created_destinations.append(row.destination_name)
        # A new destination has no aliases yet, so every alias on the row would be created. They are
        # reported even though nothing is written: a dry run that under-reports is worse than
        # useless, because the operator approves the apply on the strength of this list.
        for alias in row.aliases:
            key = normalise_place_name(alias)
            if key and key not in claimed_aliases:
                claimed_aliases.add(key)
                report.created_aliases.append(alias)
        return f"__new__{normalise_place_name(row.destination_name)}"

    destination = Destination(name=row.destination_name, code=code)
    session.add(destination)
    await session.flush()
    report.created_destinations.append(row.destination_name)
    await _add_aliases(
        session, destination.id, row.aliases, report, dry_run=False, taken=claimed_aliases
    )
    return destination.id


async def _add_aliases(
    session: AsyncSession,
    destination_id: str,
    aliases: list[str],
    report: ImportReport,
    *,
    dry_run: bool = False,
    taken: set[str] | None = None,
) -> None:
    """Attach aliases to a destination.

    Uniqueness is checked on the *normalised* alias, never on the raw text. ``"Nakuru Town"``,
    ``"nakuru town"`` and ``"nakuru   town"`` all name the same place, and the unique constraint on
    the column would happily accept all three - so without this the same place ends up claimed by
    two different destinations and quote resolution becomes ambiguous. The database compares text;
    this compares meaning.

    With ``dry_run`` the same checks run but nothing is written, so the report lists exactly the
    aliases an apply would add.
    """
    claimed = taken if taken is not None else set()
    for alias in aliases:
        key = normalise_place_name(alias)
        if not key or key in claimed:
            logger.info("alias %r is already claimed by a destination; skipped", alias)
            continue
        # Reported on both paths: the apply's report is what the operator compares against the
        # dry run they approved.
        report.created_aliases.append(alias)
        if not dry_run:
            session.add(DestinationAlias(destination_id=destination_id, alias=alias))
        claimed.add(key)
    if not dry_run:
        await session.flush()


async def _ensure_zone(
    session: AsyncSession, row: ParsedRow, report: ImportReport, *, dry_run: bool
) -> str | None:
    """Find the zone by name, else create it. Returns its id.

    Returns ``None`` when the row names no zone, and during a dry run also when the zone would have
    to be created - a dry run creates nothing, so it has no id to give back.
    """
    if not row.zone_name:
        return None
    existing = await session.scalar(select(DeliveryZone).where(DeliveryZone.name.ilike(row.zone_name)))
    if existing is not None:
        return existing.id
    if dry_run:
        report.created_zones.append(row.zone_name)
        return None
    zone = DeliveryZone(name=row.zone_name, code=row.zone_code or slug_code(row.zone_name, prefix="Z"))
    session.add(zone)
    await session.flush()
    report.created_zones.append(zone.name)
    return zone.id


async def _attach_zone(session: AsyncSession, destination_id: str, zone_id: str) -> None:
    """Point a destination at the zone its price-list row named.

    Only fills an empty zone. A zone set by hand in admin is never overwritten here: re-running an
    import must not quietly reclassify live reference data, and a destination that already has a
    zone is left exactly as the operator configured it.
    """
    destination = await session.get(Destination, destination_id)
    if destination is None:  # pragma: no cover - destination was just resolved above
        return
    if destination.zone_id == zone_id:
        return
    if destination.zone_id is not None:
        logger.info(
            "destination %r already sits in zone %s; leaving it there rather than moving it to %s",
            destination.name,
            destination.zone_id,
            zone_id,
        )
        return
    destination.zone_id = zone_id


async def _ensure_road_type(
    session: AsyncSession, row: ParsedRow, report: ImportReport, *, dry_run: bool
) -> str | None:
    if not row.road_type_name:
        return None
    existing = await session.scalar(select(RoadType).where(RoadType.name.ilike(row.road_type_name)))
    if existing is not None:
        return existing.id
    if dry_run:
        report.created_road_types.append(row.road_type_name)
        return f"__new_road__{row.road_type_name}"
    road_type = RoadType(name=row.road_type_name, code=slug_code(row.road_type_name, prefix="R"))
    session.add(road_type)
    await session.flush()
    report.created_road_types.append(road_type.name)
    return road_type.id


async def _ensure_vehicle(
    session: AsyncSession, row: ParsedRow, report: ImportReport, *, dry_run: bool
) -> str | None:
    if not row.vehicle_name:
        return None
    existing = await session.scalar(
        select(VehicleCategory).where(VehicleCategory.name.ilike(row.vehicle_name))
    )
    if existing is not None:
        return existing.id
    if dry_run:
        report.created_vehicles.append(row.vehicle_name)
        return f"__new_vehicle__{row.vehicle_name}"
    vehicle = VehicleCategory(name=row.vehicle_name, code=slug_code(row.vehicle_name, prefix="V"))
    session.add(vehicle)
    await session.flush()
    report.created_vehicles.append(vehicle.name)
    return vehicle.id
