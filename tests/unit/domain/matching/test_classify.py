"""Classification, reason selection and the symbol-conflict pass."""

from datetime import UTC, datetime

from alpaca_gatherer.domain.mapping import (
    CandidateKind,
    Horizon,
    InstrumentMapping,
    MatchStatus,
    MatchType,
    ReasonCode,
)
from alpaca_gatherer.domain.matching.checks import CandidateScore
from alpaca_gatherer.domain.matching.classify import classify, resolve_symbol_conflicts
from tests.builders import instrument

NOW = datetime(2026, 10, 8, 6, tzinfo=UTC)
EXACT, ALIAS, NAME = CandidateKind.EXACT, CandidateKind.ALIAS, CandidateKind.NAME


def passed(symbol: str, kind: CandidateKind, diff: float = 0.1) -> CandidateScore:
    return CandidateScore(
        symbol=symbol,
        kind=kind,
        active=True,
        tradable=True,
        aligned_bars=139,
        price_diff_pct=diff,
        price_tol_pct=1.05,
        direction_agreement=1.0,
        return_correlation=0.99,
        horizon=Horizon.HOURLY,
    )


def failed(
    symbol: str,
    kind: CandidateKind,
    stage: ReasonCode,
    *,
    diff: float | None = None,
    corr: float | None = None,
    active: bool = True,
) -> CandidateScore:
    return CandidateScore(
        symbol=symbol,
        kind=kind,
        active=active,
        tradable=True,
        stage=stage,
        detail=f"{stage.value} detail",
        price_diff_pct=diff,
        price_tol_pct=None if diff is None else 1.05,
        return_correlation=corr,
    )


def run(
    scores: list[CandidateScore], error: str | None = None, epic: str = "E"
) -> InstrumentMapping:
    return classify(instrument(epic), scores, error, run_id="r1", updated_at=NOW)


def test_exact_pass_wins_even_if_alias_passes() -> None:
    record = run([passed("E", EXACT, 0.5), passed("E.A", ALIAS, 0.1)])
    assert (record.status, record.match_type, record.alpaca_symbol) == (
        MatchStatus.MATCHED,
        MatchType.EXACT,
        "E",
    )
    assert record.price_diff_pct == 0.5
    assert record.reason is None
    assert len(record.candidates) == 2


def test_single_non_exact_pass_is_alias() -> None:
    record = run(
        [failed("E", EXACT, ReasonCode.FAILED_PRICE_CHECK, diff=200), passed("E.B", ALIAS)]
    )
    assert (record.status, record.match_type, record.alpaca_symbol) == (
        MatchStatus.MATCHED,
        MatchType.ALIAS,
        "E.B",
    )
    assert run([passed("BALL", NAME)]).match_type is MatchType.ALIAS


def test_several_non_exact_passes_are_ambiguous() -> None:
    record = run(
        [
            passed("E.A", ALIAS, 0.3),
            passed("E.B", ALIAS, 0.2),
            failed("E.C", ALIAS, ReasonCode.FAILED_PRICE_CHECK, diff=50),
        ]
    )
    assert record.status is MatchStatus.AMBIGUOUS
    assert record.reason is not None
    assert record.reason.code is ReasonCode.MULTIPLE_CANDIDATES
    assert record.alpaca_symbol is None
    assert record.price_diff_pct == 0.2
    assert [c.alpaca_symbol for c in record.candidates] == ["E.A", "E.B"]


def test_name_only_pass_with_unchecked_identifier_is_ambiguous() -> None:
    record = run(
        [failed("WSO.B", ALIAS, ReasonCode.INSUFFICIENT_DATA), passed("WSO", NAME, 0.62)],
        epic="WSOB",
    )
    assert record.status is MatchStatus.AMBIGUOUS
    assert record.reason is not None
    assert record.reason.code is ReasonCode.NAME_ONLY_WITH_UNCHECKED_IDENTIFIER
    assert "WSO.B" in record.reason.detail
    assert {c.alpaca_symbol for c in record.candidates} == {"WSO", "WSO.B"}


def test_unmatched_reports_furthest_candidate() -> None:
    record = run(
        [
            failed("E", EXACT, ReasonCode.INSUFFICIENT_DATA),
            failed("E.A", ALIAS, ReasonCode.FAILED_PRICE_CHECK, diff=5),
            failed("E.B", ALIAS, ReasonCode.FAILED_BEHAVIOR_CHECK, diff=0.2, corr=0.4),
        ]
    )
    assert record.status is MatchStatus.UNMATCHED
    assert record.reason is not None
    assert record.reason.code is ReasonCode.FAILED_BEHAVIOR_CHECK
    assert record.reason.detail.startswith("E.B: ")
    assert record.price_diff_pct == 0.2
    assert record.return_correlation == 0.4


def test_price_beats_data_but_exact_preferred_when_nothing_passed_price() -> None:
    record = run(
        [
            failed("E", EXACT, ReasonCode.INSUFFICIENT_DATA),
            failed("E.A", ALIAS, ReasonCode.FAILED_PRICE_CHECK, diff=5),
        ]
    )
    assert record.reason is not None
    assert record.reason.code is ReasonCode.INSUFFICIENT_DATA
    assert record.reason.detail.startswith("E: ")
    record = run(
        [
            failed("E.B", ALIAS, ReasonCode.INSUFFICIENT_DATA),
            failed("E.A", ALIAS, ReasonCode.FAILED_PRICE_CHECK, diff=5),
        ]
    )
    assert record.reason is not None
    assert record.reason.code is ReasonCode.FAILED_PRICE_CHECK


def test_not_tradable_reason() -> None:
    score = CandidateScore(
        symbol="CHSN",
        kind=EXACT,
        active=True,
        tradable=False,
        stage=ReasonCode.NOT_TRADABLE,
        detail="Alpaca asset CHSN is active, tradable=False",
        price_diff_pct=1.3,
        price_tol_pct=1.5,
    )
    record = run([score])
    assert record.reason is not None
    assert record.reason.code is ReasonCode.NOT_TRADABLE


def test_only_inactive_symbols_without_data_is_not_tradable() -> None:
    record = run(
        [
            failed("T.PRB", ALIAS, ReasonCode.INSUFFICIENT_DATA, active=False),
            failed("T.PRC", ALIAS, ReasonCode.INSUFFICIENT_DATA, active=False),
        ]
    )
    assert record.reason is not None
    assert record.reason.code is ReasonCode.NOT_TRADABLE
    assert record.reason.detail == "only inactive Alpaca symbols match (T.PRB, T.PRC)"


def test_no_candidates_is_not_listed() -> None:
    record = run([])
    assert record.reason is not None
    assert record.reason.code is ReasonCode.NOT_LISTED_ON_ALPACA


def test_capital_error_is_insufficient_data() -> None:
    error = "Capital.com has no HOUR price history for this epic (HTTP 404)"
    record = run([failed("E", EXACT, ReasonCode.INSUFFICIENT_DATA)], error)
    assert record.reason is not None
    assert record.reason.code is ReasonCode.INSUFFICIENT_DATA
    assert record.reason.detail == error


def test_symbol_conflict_makes_every_competitor_ambiguous() -> None:
    a = run([passed("X", ALIAS)], epic="A")
    b = run([passed("X", EXACT)], epic="X")
    c = run([passed("Y", EXACT)], epic="Y")
    out = {r.capital_epic: r for r in resolve_symbol_conflicts([a, b, c])}
    for epic, other in (("A", "X"), ("X", "A")):
        record = out[epic]
        assert record.status is MatchStatus.AMBIGUOUS
        assert record.alpaca_symbol is None
        assert record.match_type is None
        assert record.reason is not None
        assert record.reason.code is ReasonCode.SYMBOL_CONFLICT
        assert other in record.reason.detail
    assert out["Y"].status is MatchStatus.MATCHED


def test_no_conflict_keeps_records() -> None:
    records = [run([passed("X", EXACT)], epic="X"), run([passed("Y", EXACT)], epic="Y")]
    assert resolve_symbol_conflicts(records) == records
