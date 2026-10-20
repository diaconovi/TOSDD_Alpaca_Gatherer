"""Per-epic classification and the one-symbol-per-match conflict pass.

| Status | Rule |
|---|---|
| matched / exact | the exact candidate passes (preferred even if an alias also passes) |
| matched / alias | no exact pass; exactly one alias or name candidate passes |
| ambiguous | several non-exact candidates pass, or only a name candidate passes while an identifier
  candidate could not be checked for lack of data, or several epics match the same symbol |
| unmatched | nothing passes; the reason comes from the candidate that got furthest |
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from alpaca_gatherer.domain.mapping import (
    Candidate,
    CandidateKind,
    InstrumentMapping,
    MatchStatus,
    MatchType,
    Reason,
    ReasonCode,
)
from alpaca_gatherer.domain.matching.checks import CandidateScore
from alpaca_gatherer.domain.matching.models import CapitalInstrument

__all__ = ["classify", "resolve_symbol_conflicts", "to_candidate"]

NOT_LISTED_DETAIL = "no Alpaca symbol matches the epic, its aliases or the company name"


def to_candidate(score: CandidateScore) -> Candidate:
    """The stored form of a candidate score."""
    return Candidate(
        alpaca_symbol=score.symbol,
        kind=score.kind,
        tradable=score.tradable,
        active=score.active,
        passed=score.passed,
        aligned_bars=score.aligned_bars,
        price_diff_pct=score.price_diff_pct,
        direction_agreement=score.direction_agreement,
        return_correlation=score.return_correlation,
        horizon=score.horizon,
        failed_check=score.failed_check,
    )


def classify(
    instrument: CapitalInstrument,
    scores: Sequence[CandidateScore],
    capital_error: str | None,
    *,
    run_id: str,
    updated_at: datetime,
) -> InstrumentMapping:
    """Classify one epic from its candidate scores."""
    base = InstrumentMapping(
        capital_epic=instrument.epic,
        status=MatchStatus.UNMATCHED,
        reason=Reason(ReasonCode.NOT_LISTED_ON_ALPACA, NOT_LISTED_DETAIL),
        run_id=run_id,
        updated_at=updated_at,
        capital_symbol=instrument.symbol,
        capital_name=instrument.name,
        source=instrument.source,
        candidates=tuple(to_candidate(s) for s in scores),
    )
    if not scores:
        return base

    def fill(record: InstrumentMapping, s: CandidateScore) -> InstrumentMapping:
        return replace(
            record,
            price_diff_pct=s.price_diff_pct,
            direction_agreement=s.direction_agreement,
            return_correlation=s.return_correlation,
            horizon=s.horizon,
        )

    def unmatched(s: CandidateScore, code: ReasonCode, detail: str) -> InstrumentMapping:
        return fill(replace(base, reason=Reason(code, detail)), s)

    def matched(s: CandidateScore, match_type: MatchType) -> InstrumentMapping:
        record = replace(
            base, status=MatchStatus.MATCHED, reason=None, alpaca_symbol=s.symbol,
            match_type=match_type,
        )  # fmt: skip
        return fill(record, s)

    def ambiguous(
        s: CandidateScore, code: ReasonCode, detail: str, shown: Sequence[CandidateScore]
    ) -> InstrumentMapping:
        record = replace(
            base,
            status=MatchStatus.AMBIGUOUS,
            reason=Reason(code, detail),
            candidates=tuple(to_candidate(c) for c in shown),
        )
        return fill(record, s)

    if capital_error:
        return unmatched(scores[0], ReasonCode.INSUFFICIENT_DATA, capital_error)

    passed = [s for s in scores if s.passed]
    if passed:
        exact = next((s for s in passed if s.kind is CandidateKind.EXACT), None)
        if exact is not None:
            return matched(exact, MatchType.EXACT)
        unverified = [
            s
            for s in scores
            if s.kind is not CandidateKind.NAME and s.stage is ReasonCode.INSUFFICIENT_DATA
        ]
        if len(passed) == 1 and passed[0].kind is CandidateKind.NAME and unverified:
            ids = ", ".join(s.symbol for s in unverified)
            return ambiguous(
                passed[0],
                ReasonCode.NAME_ONLY_WITH_UNCHECKED_IDENTIFIER,
                f"name match {passed[0].symbol} passes but identifier candidate(s) {ids} "
                "have no data to compare",
                [*passed, *unverified],
            )
        if len(passed) == 1:
            return matched(passed[0], MatchType.ALIAS)
        best = min(passed, key=lambda s: s.price_diff_pct or 0)
        listed = ", ".join(
            f"{s.symbol} (diff {s.price_diff_pct}%, corr {s.return_correlation})" for s in passed
        )
        return ambiguous(
            best, ReasonCode.MULTIPLE_CANDIDATES, f"several candidates pass: {listed}", passed
        )

    inactive_only = all(not s.active for s in scores)
    best = max(
        scores,
        key=lambda s: (s.progress, s.return_correlation or -1, -(s.price_diff_pct or 1e9)),
    )
    exact = next((s for s in scores if s.kind is CandidateKind.EXACT), None)
    if exact is not None and best.progress <= 1:
        best = exact  # nothing got past price: the exact-symbol story is the informative one
    if inactive_only and best.stage is ReasonCode.INSUFFICIENT_DATA:
        symbols = ", ".join(s.symbol for s in scores)
        return unmatched(
            best, ReasonCode.NOT_TRADABLE, f"only inactive Alpaca symbols match ({symbols})"
        )
    assert best.stage is not None
    return unmatched(best, best.stage, f"{best.symbol}: {best.detail}")


def resolve_symbol_conflicts(records: Sequence[InstrumentMapping]) -> list[InstrumentMapping]:
    """Reclassify every epic matched to a symbol that another epic also matched.

    All competing epics become ``ambiguous`` with reason ``symbol_conflict`` listing the others,
    so that a matched symbol belongs to at most one epic (research R15).
    """
    by_symbol: dict[str, list[str]] = defaultdict(list)
    for record in records:
        if record.status is MatchStatus.MATCHED and record.alpaca_symbol:
            by_symbol[record.alpaca_symbol].append(record.capital_epic)
    conflicts = {symbol: epics for symbol, epics in by_symbol.items() if len(epics) > 1}
    if not conflicts:
        return list(records)
    out: list[InstrumentMapping] = []
    for original in records:
        record = original
        symbol = record.alpaca_symbol
        if record.status is MatchStatus.MATCHED and symbol in conflicts:
            others = ", ".join(e for e in conflicts[symbol] if e != record.capital_epic)
            record = replace(
                original,
                status=MatchStatus.AMBIGUOUS,
                alpaca_symbol=None,
                match_type=None,
                reason=Reason(
                    ReasonCode.SYMBOL_CONFLICT, f"{symbol} is also matched by epic(s) {others}"
                ),
                candidates=tuple(c for c in record.candidates if c.passed),
            )
        out.append(record)
    return out
