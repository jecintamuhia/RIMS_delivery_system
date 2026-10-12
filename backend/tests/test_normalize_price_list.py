"""Tests for the wide price-list normaliser.

The wide export is business data RIMs sends by hand, so the parser's job is to convert layout
without ever touching the values: a place name is copied verbatim and a price is copied verbatim.
These tests pin that down, plus the failure modes that would otherwise show up as a silently wrong
price list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.normalize_price_list import (
    Conversion,
    Entry,
    NormaliseError,
    read_wide_export,
    write_canonical,
)
from app.services.pricing.import_csv import REQUIRED_COLUMNS, parse_csv

EXPORT = """RIMS SUPPLIES CO.LTD
P.O BOX 13333(20100)
NAKURU
TRANSPORT COSTS
PLACE,AMOUNT,PLACE,AMOUNT,PLACE,AMOUNT
MURUNGARU,3000,KENTON,4500,HIGH PEAK,1200
KIRIMA,2500,KAMERE,3000,MASTIMA,1500
SUGUTI/THUITY,9000,KENGEN,5000,SERU,4500
KEDONG,3000,SANTUARY,1500,,
"""


def _write(tmp_path: Path, text: str = EXPORT) -> Path:
    path = tmp_path / "export.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _prices(conversion: Conversion) -> dict[str, str]:
    return {entry.place: str(entry.amount) for entry in conversion.entries}


def test_the_letterhead_and_title_rows_are_skipped(tmp_path: Path) -> None:
    conversion = read_wide_export(_write(tmp_path))

    assert len(conversion.entries) == 11
    assert not any("RIMS SUPPLIES" in entry.place for entry in conversion.entries)
    assert not any("P.O BOX" in entry.place for entry in conversion.entries)


def test_every_price_pair_on_a_row_is_read(tmp_path: Path) -> None:
    prices = _prices(read_wide_export(_write(tmp_path)))

    assert prices["MURUNGARU"] == "3000"
    assert prices["KENTON"] == "4500"
    assert prices["HIGH PEAK"] == "1200"
    assert prices["SERU"] == "4500"


def test_a_trailing_empty_column_is_not_a_price(tmp_path: Path) -> None:
    """The last row ends in ``,,``; reading that as a place would create a nameless destination."""
    prices = _prices(read_wide_export(_write(tmp_path)))

    assert prices["KEDONG"] == "3000"
    assert prices["SANTUARY"] == "1500"
    assert len(prices) == 11


def test_place_names_are_copied_exactly_as_spelled(tmp_path: Path) -> None:
    """A “helpful” correction would point the price at a different place."""
    prices = _prices(read_wide_export(_write(tmp_path)))

    assert "SUGUTI/THUITY" in prices
    assert "SUGUTI THUITY" not in prices


def test_an_unexpected_character_is_reported_but_not_rewritten(tmp_path: Path) -> None:
    conversion = read_wide_export(
        _write(tmp_path, EXPORT.replace("MURUNGARU,3000", "G!TUAMBA,1000"))
    )

    entry = next(e for e in conversion.entries if "TUAMBA" in e.place)
    assert entry.place == "G!TUAMBA"
    assert entry.warnings


def test_a_typo_is_not_corrected_away(tmp_path: Path) -> None:
    conversion = read_wide_export(_write(tmp_path, EXPORT.replace("KIRIMA", "KIRIMAA")))

    assert "KIRIMAA" in _prices(conversion)
    assert "KIRIMA" not in _prices(conversion)


def test_a_vague_place_name_is_flagged_for_review(tmp_path: Path) -> None:
    conversion = read_wide_export(_write(tmp_path, EXPORT.replace("HIGH PEAK", "FLYOVER")))

    entry = next(e for e in conversion.entries if e.place == "FLYOVER")
    assert any("vague" in warning for warning in entry.warnings)


def test_a_second_header_row_is_rejected(tmp_path: Path) -> None:
    doubled = EXPORT + "PLACE,AMOUNT\nX,1\n"

    with pytest.raises(NormaliseError, match="second PLACE/AMOUNT header"):
        read_wide_export(_write(tmp_path, doubled))


def test_an_odd_number_of_cells_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NormaliseError, match="odd number of cells"):
        read_wide_export(_write(tmp_path, EXPORT.replace("KIRIMA,2500", "KIRIMA,2500,KAMERE")))


def test_more_columns_than_the_header_declared_is_rejected(tmp_path: Path) -> None:
    text = EXPORT.replace("PLACE,AMOUNT,PLACE,AMOUNT,PLACE,AMOUNT", "PLACE,AMOUNT,PLACE,AMOUNT")
    text += "EXTRA,100,EXTRA2,200,EXTRA3,300,EXTRA4,400\n"

    with pytest.raises(NormaliseError, match="more price columns"):
        read_wide_export(_write(tmp_path, text))


@pytest.mark.parametrize("amount", ["", "abc", "-100", "0"])
def test_an_unusable_amount_is_rejected(tmp_path: Path, amount: str) -> None:
    with pytest.raises(NormaliseError, match="amount"):
        read_wide_export(_write(tmp_path, EXPORT.replace("3000,KENTON", f"{amount},KENTON")))


def test_a_price_without_a_place_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NormaliseError, match="no place name"):
        read_wide_export(_write(tmp_path, EXPORT.replace("MURUNGARU,3000", ",3000")))


def test_data_before_the_header_is_rejected(tmp_path: Path) -> None:
    """A file with no header must fail loudly rather than be half-imported."""
    with pytest.raises(NormaliseError, match="before the PLACE/AMOUNT header"):
        read_wide_export(_write(tmp_path, "MURUNGARU,3000,KENTON,4500\n"))


def test_a_file_with_no_header_at_all_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NormaliseError, match="no PLACE/AMOUNT header"):
        read_wide_export(_write(tmp_path, "RIMS SUPPLIES CO.LTD\nNAKURU\n"))


def test_a_file_with_no_prices_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NormaliseError, match="no prices"):
        read_wide_export(_write(tmp_path, "TITLE\nPLACE,AMOUNT\n"))


def test_duplicate_places_are_detected_regardless_of_case_and_spacing(tmp_path: Path) -> None:
    text = EXPORT + "murungaru,3000\n"

    conversion = read_wide_export(_write(tmp_path, text))

    duplicates = conversion.duplicates
    assert len(duplicates) == 1
    place, first_line, second_line = duplicates[0]
    assert place.upper() == "MURUNGARU"
    assert second_line > first_line


def test_the_canonical_file_matches_what_the_importer_expects(tmp_path: Path) -> None:
    """The end-to-end promise: what this tool writes, the importer can read unchanged."""
    conversion = read_wide_export(_write(tmp_path))
    target = write_canonical(conversion.entries, tmp_path / "canonical.csv", force=False)

    parsed = parse_csv(target, default_effective_from=__import__("datetime").date(2026, 10, 5))

    assert not parsed.problems, parsed.problems
    assert len(parsed.rows) == len(conversion.entries)
    assert list(REQUIRED_COLUMNS) == ["destination_name", "base_price"]
    assert {row.destination_name for row in parsed.rows} == set(_prices(conversion))


def test_writing_refuses_to_clobber_an_existing_price_list(tmp_path: Path) -> None:
    conversion = read_wide_export(_write(tmp_path))
    target = tmp_path / "canonical.csv"
    write_canonical(conversion.entries, target, force=False)

    with pytest.raises(NormaliseError, match="already exists"):
        write_canonical(conversion.entries, target, force=False)

    write_canonical(conversion.entries, target, force=True)


def test_amounts_keep_their_exact_value(tmp_path: Path) -> None:
    """A price must survive the round trip unchanged; KES 0.5 is not the same as KES 5."""
    conversion = Conversion(
        entries=[Entry(line=6, place="A", amount=__import__("decimal").Decimal("0.5"))]
    )
    target = write_canonical(conversion.entries, tmp_path / "out.csv", force=False)

    assert target.read_text(encoding="utf-8").splitlines() == ["destination_name,base_price", "A,0.5"]
