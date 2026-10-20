"""Mapping record invariants (data-model.md §1)."""

from datetime import UTC, datetime

import pytest

from alpaca_gatherer.domain.mapping import (
    AMBIGUOUS_REASONS,
    UNMATCHED_REASONS,
    InstrumentMapping,
    InvalidMapping,
    MatchStatus,
    MatchType,
    Reason,
    ReasonCode,
)

NOW = datetime(2026, 10, 8, 6, tzinfo=UTC)


def make(**kwargs: object) -> InstrumentMapping:
    values: dict[str, object] = {"capital_epic": "BRKB", "run_id": "r1", "updated_at": NOW}
    values.update(kwargs)
    # The test builds records from loose keyword values on purpose to probe the invariants.
    return InstrumentMapping(**values)  # type: ignore[arg-type]


def test_matched_needs_symbol_and_type_and_no_reason() -> None:
    record = make(status=MatchStatus.MATCHED, alpaca_symbol="BRK.B", match_type=MatchType.ALIAS)
    assert record.reason is None
    with pytest.raises(InvalidMapping):
        make(status=MatchStatus.MATCHED, match_type=MatchType.EXACT)
    with pytest.raises(InvalidMapping):
        make(status=MatchStatus.MATCHED, alpaca_symbol="BRK.B")
    with pytest.raises(InvalidMapping):
        make(
            status=MatchStatus.MATCHED,
            alpaca_symbol="BRK.B",
            match_type=MatchType.EXACT,
            reason=Reason(ReasonCode.NOT_TRADABLE, "x"),
        )


@pytest.mark.parametrize("status", [MatchStatus.AMBIGUOUS, MatchStatus.UNMATCHED])
def test_non_matched_has_no_symbol_or_type_and_needs_reason(status: MatchStatus) -> None:
    code = (
        ReasonCode.MULTIPLE_CANDIDATES
        if status is MatchStatus.AMBIGUOUS
        else ReasonCode.NOT_TRADABLE
    )
    assert make(status=status, reason=Reason(code, "detail")).alpaca_symbol is None
    with pytest.raises(InvalidMapping):
        make(status=status)
    with pytest.raises(InvalidMapping):
        make(status=status, reason=Reason(code, "d"), alpaca_symbol="X")
    with pytest.raises(InvalidMapping):
        make(status=status, reason=Reason(code, "d"), match_type=MatchType.ALIAS)


def test_reason_sets() -> None:
    assert {c.value for c in AMBIGUOUS_REASONS} == {
        "multiple_candidates",
        "name_only_with_unchecked_identifier",
        "symbol_conflict",
    }
    assert {c.value for c in UNMATCHED_REASONS} == {
        "not_listed_on_alpaca",
        "not_tradable",
        "insufficient_data",
        "failed_price_check",
        "failed_behavior_check",
    }


@pytest.mark.parametrize("code", sorted(UNMATCHED_REASONS))
def test_ambiguous_rejects_unmatched_reasons(code: ReasonCode) -> None:
    with pytest.raises(InvalidMapping):
        make(status=MatchStatus.AMBIGUOUS, reason=Reason(code, "d"))


@pytest.mark.parametrize("code", sorted(AMBIGUOUS_REASONS))
def test_unmatched_rejects_ambiguous_reasons(code: ReasonCode) -> None:
    with pytest.raises(InvalidMapping):
        make(status=MatchStatus.UNMATCHED, reason=Reason(code, "d"))


def test_empty_epic_rejected() -> None:
    with pytest.raises(InvalidMapping):
        make(
            capital_epic="",
            status=MatchStatus.UNMATCHED,
            reason=Reason(ReasonCode.NOT_TRADABLE, "d"),
        )


def test_matched_factory_normalizes_to_utc() -> None:
    record = InstrumentMapping.matched(
        capital_epic="TSLA",
        alpaca_symbol="TSLA",
        match_type=MatchType.EXACT,
        run_id="r",
        updated_at=NOW,
    )
    assert record.updated_at.tzinfo is UTC
