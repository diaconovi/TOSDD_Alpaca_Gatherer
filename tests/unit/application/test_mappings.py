"""Lookup use case (data-model.md §1, lookup rules)."""

import pytest

from alpaca_gatherer.application.mappings import LookupMapping
from alpaca_gatherer.domain.errors import InstrumentNotFound, InvalidRequest, MappingNotAvailable
from alpaca_gatherer.domain.mapping import MatchStatus
from tests.fakes import InMemoryMappingRepository
from tests.samples import ambiguous, matched, unmatched


@pytest.fixture
def lookup() -> LookupMapping:
    return LookupMapping(
        InMemoryMappingRepository([matched(), unmatched(), ambiguous(), matched("TSLA", "TSLA")])
    )


@pytest.mark.parametrize(
    ("epic", "symbol"), [("BRKB", "BRK.B"), (None, None), ("", None), (None, "")]
)
async def test_exactly_one_identifier_required(
    lookup: LookupMapping, epic: str | None, symbol: str | None
) -> None:
    with pytest.raises(InvalidRequest) as info:
        await lookup(capital_epic=epic, alpaca_symbol=symbol)
    assert "exactly one" in info.value.message


async def test_epic_lookup_returns_any_status(lookup: LookupMapping) -> None:
    assert (await lookup(capital_epic="BRKB")).alpaca_symbol == "BRK.B"
    assert (await lookup(capital_epic="APPL")).status is MatchStatus.UNMATCHED


async def test_ambiguous_epic_has_no_symbol_but_candidates(lookup: LookupMapping) -> None:
    record = await lookup(capital_epic="WSOB")
    assert record.status is MatchStatus.AMBIGUOUS
    assert record.alpaca_symbol is None
    assert [c.alpaca_symbol for c in record.candidates] == ["WSO", "WSO.B"]


async def test_symbol_lookup_finds_matched_epic(lookup: LookupMapping) -> None:
    assert (await lookup(alpaca_symbol="BRK.B")).capital_epic == "BRKB"


async def test_symbol_only_ambiguous_candidate_is_not_found(lookup: LookupMapping) -> None:
    with pytest.raises(InstrumentNotFound):
        await lookup(alpaca_symbol="WSO")


async def test_unknown_epic_is_not_found(lookup: LookupMapping) -> None:
    with pytest.raises(InstrumentNotFound, match="ZZZZ"):
        await lookup(capital_epic="ZZZZ")


async def test_no_snapshot_is_mapping_not_available() -> None:
    lookup = LookupMapping(InMemoryMappingRepository())
    with pytest.raises(MappingNotAvailable):
        await lookup(capital_epic="BRKB")
    with pytest.raises(MappingNotAvailable):
        await lookup(alpaca_symbol="BRK.B")
