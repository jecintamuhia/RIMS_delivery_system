"""Normalise RIMs' wide price list into the canonical import layout.

Usage::

    python -m app.cli.normalize_price_list <source.csv> [--out NAME] [--force]

RIMs sends the transport cost list as a *wide* spreadsheet export: a letterhead preamble, a
``PLACE,AMOUNT,PLACE,AMOUNT,...`` header, and then up to three price pairs per row::

    RIMS SUPPLIES CO.LTD
    ...
    PLACE,AMOUNT,PLACE,AMOUNT,PLACE,AMOUNT
    MURUNGARU,3000,KENTON,4500,HIGH PEAK,1200

The importer (:mod:`app.services.pricing.import_csv`) deliberately reads one destination per row,
because that is the shape the pricing rules are stored in. Rather than teach the importer a second
layout - and risk the two quietly disagreeing - this converts the export to the canonical file and
leaves it in ``data/pricing`` for the operator to import and review.

The conversion is deliberately literal. Place names are copied exactly as RIMs spelled them: this
is business data, and a "helpful" correction would silently repoint a price at a different place.
Suspect spellings and duplicate places are *reported*, never rewritten.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.services.pricing.import_csv import REQUIRED_COLUMNS, pricing_data_dir

#: How many ``PLACE,AMOUNT`` pairs the widest row may contain.
MAX_PAIRS_PER_ROW = 8

#: Names with no distinguishing letters are common in a local price list but are the ones most
#: likely to geocode to the wrong place, so they are called out rather than quietly imported.
VAGUE_PLACES = {
    "TOWN AREA",
    "JUNCTION",
    "FLYOVER",
    "VI",
    "DCK",
    "SLAUGHTER",
    "KIBUNGO",
    "MAIN",
    "OTHER",
}


class NormaliseError(Exception):
    """The export cannot be converted without a human decision."""


@dataclass
class Entry:
    """One ``PLACE -> AMOUNT`` price."""

    line: int
    place: str
    amount: Decimal
    warnings: list[str] = field(default_factory=list)


@dataclass
class Conversion:
    entries: list[Entry]
    warnings: list[str] = field(default_factory=list)

    @property
    def duplicates(self) -> list[tuple[str, int, int]]:
        seen: dict[str, int] = {}
        found: list[tuple[str, int, int]] = []
        for entry in self.entries:
            key = _key(entry.place)
            if key in seen:
                found.append((entry.place, seen[key], entry.line))
            else:
                seen[key] = entry.line
        return found


def _key(value: str) -> str:
    return " ".join(value.upper().split())


def _is_header(cells: list[str]) -> bool:
    """True for a ``PLACE,AMOUNT`` repeated header of any width."""
    lowered = [cell.strip().lower() for cell in cells]
    if len(lowered) < 2 or len(lowered) % 2 != 0:
        return False
    return all(
        name == "place" and value == "amount"
        for name, value in zip(lowered[0::2], lowered[1::2], strict=True)
    )


def _amount(raw: str, line: int, place: str) -> Decimal:
    try:
        value = Decimal(raw.strip().replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise NormaliseError(f"line {line}: “{place}” has an unreadable amount {raw!r}") from exc
    if value <= 0:
        raise NormaliseError(f"line {line}: “{place}” has a non-positive amount {raw!r}")
    return value


def _warn_about(place: str) -> list[str]:
    """Flag a place name a human should confirm before the prices go live."""
    warnings: list[str] = []
    unusual = sorted({ch for ch in place if not (ch.isalnum() or ch in " -/'&.")})
    if unusual:
        warnings.append(f"contains unexpected character(s) {''.join(unusual)!r}")
    if place.upper() in VAGUE_PLACES or (len(place) <= 3 and "/" not in place):
        warnings.append("is a vague place name that may not geocode to one location")
    if place != place.strip() or "  " in place:
        warnings.append("has irregular spacing")
    return warnings


def read_wide_export(path: Path) -> Conversion:
    """Parse the wide export. Every problem is collected so one pass tells us everything."""
    entries: list[Entry] = []
    warnings: list[str] = []
    header_pairs: int | None = None

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    for number, cells in enumerate(rows, start=1):
        if not any(cell.strip() for cell in cells):
            continue

        if _is_header(cells):
            if header_pairs is not None:
                raise NormaliseError(f"line {number}: a second PLACE/AMOUNT header was found")
            header_pairs = len(cells) // 2
            if header_pairs > MAX_PAIRS_PER_ROW:
                raise NormaliseError(
                    f"line {number}: {header_pairs} price columns exceeds the supported "
                    f"{MAX_PAIRS_PER_ROW}"
                )
            continue

        if header_pairs is None:
            # Letterhead and title rows carry no prices; they are skipped, not guessed at.
            if len(cells) == 1:
                continue
            raise NormaliseError(
                f"line {number}: data appears before the PLACE/AMOUNT header: {cells!r}"
            )

        if len(cells) % 2 != 0:
            raise NormaliseError(f"line {number}: row has an odd number of cells: {cells!r}")
        if len(cells) // 2 > header_pairs:
            raise NormaliseError(
                f"line {number}: row has more price columns than the header declared: {cells!r}"
            )

        for index in range(0, len(cells), 2):
            place, amount = cells[index].strip(), cells[index + 1]
            if not place and not amount.strip():
                continue  # trailing blank column
            if not place:
                raise NormaliseError(f"line {number}: a price of {amount!r} has no place name")
            entries.append(
                Entry(line=number, place=place, amount=_amount(amount, number, place),
                      warnings=_warn_about(place))
            )

    if header_pairs is None:
        raise NormaliseError("no PLACE/AMOUNT header row was found")
    if not entries:
        raise NormaliseError("the export contains no prices")

    return Conversion(entries=entries, warnings=warnings)


def write_canonical(entries: Sequence[Entry], target: Path, *, force: bool) -> Path:
    """Write the canonical CSV the importer can read. Refuses to clobber silently."""
    if target.exists() and not force:
        raise NormaliseError(
            f"{target.name} already exists; pass --force to replace it (it holds live prices)."
        )
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(REQUIRED_COLUMNS)
        for entry in entries:
            writer.writerow([entry.place, str(entry.amount)])
    return target


def _report(conversion: Conversion, source: Path, target: Path) -> None:
    amounts = sorted(entry.amount for entry in conversion.entries)
    total = sum(amounts)
    print(f"Read {len(conversion.entries)} prices from {source.name}")
    print(f"Places: {len(conversion.entries)} unique, {amounts[0]:,} to {amounts[-1]:,} KES, {total:,} total")
    print(f"Wrote canonical price list: {target}")

    duplicates = conversion.duplicates
    if duplicates:
        print("\nDUPLICATE places (import refused until these are resolved):")
        for place, first, again in duplicates:
            print(f"  {place}: lines {first} and {again}")

    flagged = [(entry.place, entry.line, entry.warnings) for entry in conversion.entries if entry.warnings]
    if flagged:
        print(f"\n{len(flagged)} place name(s) to confirm before activation (left exactly as RIMs spelled them):")
        for place, line, reasons in flagged:
            print(f"  line {line}: {place} - {'; '.join(reasons)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="RIMs' wide price list export")
    parser.add_argument(
        "--out",
        default=None,
        help=f"canonical file name inside {pricing_data_dir()} (default: derived from the source)",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing canonical file")
    args = parser.parse_args(argv)

    source: Path = args.source
    if not source.is_file():
        print(f"No such file: {source}", file=sys.stderr)
        return 2

    try:
        conversion = read_wide_export(source)
        name = args.out or f"{source.stem}.csv"
        target = write_canonical(conversion.entries, pricing_data_dir() / name, force=args.force)
    except NormaliseError as exc:
        print(f"Cannot convert {source.name}: {exc}", file=sys.stderr)
        return 1

    _report(conversion, source, target)
    return 1 if conversion.duplicates else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
