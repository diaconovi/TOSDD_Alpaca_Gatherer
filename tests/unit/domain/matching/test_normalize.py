"""Normalization and aliasing (matching-process: candidate generation)."""

import pytest

from alpaca_gatherer.domain.matching.normalize import (
    capital_aliases,
    class_root,
    compact_key,
    normalize_name,
    sweep_epics,
)


@pytest.mark.parametrize("spelling", ["BRK.B", "BRK/B", "BRKb", "BRK B", "brk.b"])
def test_compact_key_unifies_spellings(spelling: str) -> None:
    assert compact_key(spelling) == "BRKB"


@pytest.mark.parametrize(
    ("epic", "symbol", "expected"),
    [
        ("AXONUS", "AXONus", "AXON"),
        ("NLOPUS", "NLOP US", "NLOP"),
        ("MTUS", "MTus", "MT"),
    ],
)
def test_us_suffix_is_stripped(epic: str, symbol: str, expected: str) -> None:
    aliases = capital_aliases(epic, symbol)
    assert expected in aliases
    assert epic in aliases


def test_us_suffix_only_stripped_from_lowercase_marker() -> None:
    # "MTUS" spelled in capitals is Metallus' ticker on Alpaca: not a US-line marker.
    assert capital_aliases("MTUS", "MTUS") == {"MTUS"}


@pytest.mark.parametrize(
    ("epic", "symbol", "expected"),
    [("HEIA", "HEIa", "HEI.A"), ("BRKB", "BRKb", "BRK.B"), ("BFBUS", "BFbus", "BF.B")],
)
def test_trailing_lowercase_letter_is_a_share_class(epic: str, symbol: str, expected: str) -> None:
    assert expected in capital_aliases(epic, symbol)


def test_slash_becomes_dot() -> None:
    assert "GME.WS" in capital_aliases("GMEWS", "GME/WS")


def test_missing_symbol_falls_back_to_epic() -> None:
    assert capital_aliases("TSLA", None) == {"TSLA"}


def test_class_root() -> None:
    assert class_root("BRK.A") == "BRK"
    assert class_root("BRK.B") == "BRK"
    assert class_root("BRK") is None


def test_sweep_epics_from_symbols() -> None:
    assert sweep_epics(["BRK.B", "TSLA"]) == {"BRKB", "BRKBUS", "TSLA", "TSLAUS"}
    assert sweep_epics(["..."]) == set()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Berkshire Hathaway Inc - B ", "berkshire hathaway b"),
        ("Commerce.com Inc", "commerce com"),
        ("Taiwan Semiconductor Manufacturing Co Ltd ADR", "taiwan semiconductor manufacturing"),
        ("AT&T Inc.", "at and t"),
        ("Alphabet Inc. Class A Common Stock", "alphabet a"),
    ],
)
def test_name_normalization(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected
