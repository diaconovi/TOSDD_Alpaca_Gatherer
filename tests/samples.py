"""Sample mapping records shared by unit and integration tests."""

from datetime import UTC, datetime

from alpaca_gatherer.domain.mapping import (
    Candidate,
    CandidateKind,
    FailedCheck,
    Horizon,
    InstrumentMapping,
    MatchStatus,
    MatchType,
    Reason,
    ReasonCode,
    Source,
)

UPDATED_AT = datetime(2026, 10, 8, 6, 30, tzinfo=UTC)


def matched(epic: str = "BRKB", symbol: str = "BRK.B", run_id: str = "run-1") -> InstrumentMapping:
    return InstrumentMapping(
        capital_epic=epic,
        status=MatchStatus.MATCHED,
        alpaca_symbol=symbol,
        match_type=MatchType.ALIAS if epic != symbol else MatchType.EXACT,
        run_id=run_id,
        updated_at=UPDATED_AT,
        capital_symbol=epic,
        capital_name="Berkshire Hathaway Inc",
        source=Source.CATALOG,
        candidates=(
            Candidate(
                alpaca_symbol=symbol,
                kind=CandidateKind.ALIAS,
                tradable=True,
                active=True,
                passed=True,
                aligned_bars=139,
                price_diff_pct=0.02,
                direction_agreement=1.0,
                return_correlation=0.99,
                horizon=Horizon.HOURLY,
            ),
        ),
        price_diff_pct=0.02,
        direction_agreement=1.0,
        return_correlation=0.99,
        horizon=Horizon.HOURLY,
    )


def unmatched(epic: str = "APPL", run_id: str = "run-1") -> InstrumentMapping:
    return InstrumentMapping(
        capital_epic=epic,
        status=MatchStatus.UNMATCHED,
        reason=Reason(
            ReasonCode.NOT_LISTED_ON_ALPACA,
            "no Alpaca symbol matches the epic, its aliases or the company name",
        ),
        run_id=run_id,
        updated_at=UPDATED_AT,
        source=Source.SWEEP,
    )


def ambiguous(epic: str = "WSOB", symbols: tuple[str, ...] = ("WSO", "WSO.B")) -> InstrumentMapping:
    return InstrumentMapping(
        capital_epic=epic,
        status=MatchStatus.AMBIGUOUS,
        reason=Reason(ReasonCode.MULTIPLE_CANDIDATES, "several candidates pass"),
        run_id="run-1",
        updated_at=UPDATED_AT,
        candidates=tuple(
            Candidate(
                alpaca_symbol=s,
                kind=CandidateKind.NAME,
                tradable=True,
                active=True,
                passed=True,
                aligned_bars=120,
                price_diff_pct=0.6,
                direction_agreement=0.89,
                return_correlation=0.94,
                horizon=Horizon.SESSION,
                failed_check=None if s == "WSO" else FailedCheck.DATA,
            )
            for s in symbols
        ),
        price_diff_pct=0.6,
        direction_agreement=0.89,
        return_correlation=0.94,
        horizon=Horizon.SESSION,
    )
