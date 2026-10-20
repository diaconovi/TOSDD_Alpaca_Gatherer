"""The pure matching pipeline, in three steps so the caller fetches only the bars it needs.

1. ``build_plan`` generates identifier candidates for every epic (and name candidates for epics
   without any), which says which epics and symbols need bars.
2. ``name_candidates_needed`` scores identifier candidates and adds name candidates for epics where
   none passed the price check; it returns the symbols whose bars are additionally needed.
3. ``match_universe`` scores, classifies and resolves symbol conflicts.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from alpaca_gatherer.domain.mapping import InstrumentMapping
from alpaca_gatherer.domain.matching.candidates import AlpacaIndex, CandidateRef
from alpaca_gatherer.domain.matching.checks import CandidateScore, no_data_score, score_candidate
from alpaca_gatherer.domain.matching.classify import classify, resolve_symbol_conflicts
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalHistory,
    CapitalInstrument,
    Session,
)
from alpaca_gatherer.domain.matching.window import SessionLocator
from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = [
    "EpicPlan",
    "MatchingPlan",
    "build_plan",
    "match_universe",
    "name_candidates_needed",
]

NO_CAPITAL_BARS = "Capital.com returned no bars in window"


@dataclass(slots=True)
class EpicPlan:
    """Candidates of one epic; ``name`` is ``None`` until name candidates are computed."""

    instrument: CapitalInstrument
    identifier: list[CandidateRef]
    name: list[CandidateRef] | None = None

    @property
    def has_candidates(self) -> bool:
        """True if at least one candidate is known."""
        return bool(self.identifier or self.name)


@dataclass(slots=True)
class MatchingPlan:
    """Candidates of every epic of the universe."""

    index: AlpacaIndex
    epics: dict[str, EpicPlan]
    thresholds: Thresholds

    def epics_needing_history(self) -> list[str]:
        """Epics with at least one candidate (the others are ``not_listed_on_alpaca``)."""
        return [epic for epic, plan in self.epics.items() if plan.has_candidates]

    def symbols(self) -> set[str]:
        """Every candidate symbol known so far."""
        out: set[str] = set()
        for plan in self.epics.values():
            out.update(c.symbol for c in plan.identifier)
            out.update(c.symbol for c in plan.name or ())
        return out

    def compute_names(self, plan: EpicPlan) -> list[CandidateRef]:
        """Compute (once) the name candidates of an epic, excluding its identifier symbols."""
        if plan.name is None:
            c = self.thresholds.candidates
            plan.name = self.index.name_candidates(
                plan.instrument,
                c.name_ratio,
                c.max_name_candidates,
                exclude={x.symbol for x in plan.identifier},
            )
        return plan.name


def build_plan(
    universe: Sequence[CapitalInstrument], assets: Sequence[AlpacaAsset], thresholds: Thresholds
) -> MatchingPlan:
    """Generate identifier candidates for every epic and name candidates where there are none."""
    plan = MatchingPlan(AlpacaIndex(assets), {}, thresholds)
    for instrument in universe:
        epic_plan = EpicPlan(instrument, plan.index.identifier_candidates(instrument))
        if not epic_plan.identifier:
            plan.compute_names(epic_plan)
        plan.epics[instrument.epic] = epic_plan
    return plan


def _history_error(history: CapitalHistory | None) -> str | None:
    if history is None:
        return NO_CAPITAL_BARS
    if history.error:
        return history.error
    return None if history.bars else NO_CAPITAL_BARS


def _score_all(
    refs: Iterable[CandidateRef],
    history: CapitalHistory,
    error: str | None,
    bars_by_symbol: Mapping[str, Sequence[AlpacaBar]],
    locator: SessionLocator,
    n_sessions: int,
    thresholds: Thresholds,
) -> list[CandidateScore]:
    if error:
        return [no_data_score(ref, error) for ref in refs]
    return [
        score_candidate(
            ref, history.bars, bars_by_symbol.get(ref.symbol), locator, n_sessions, thresholds
        )
        for ref in refs
    ]


def name_candidates_needed(
    plan: MatchingPlan,
    histories: Mapping[str, CapitalHistory],
    bars_by_symbol: Mapping[str, Sequence[AlpacaBar]],
    sessions: Sequence[Session],
) -> set[str]:
    """Add name candidates where no identifier candidate passed price; return their symbols.

    Only symbols of epics with Capital.com history are returned (the others cannot be compared).
    """
    locator = SessionLocator(sessions)
    needed: set[str] = set()
    for epic, epic_plan in plan.epics.items():
        history = histories.get(epic)
        error = _history_error(history)
        if epic_plan.name is None:
            scores = _score_all(
                epic_plan.identifier,
                history or CapitalHistory(),
                error,
                bars_by_symbol,
                locator,
                len(sessions),
                plan.thresholds,
            )
            if any(s.price_ok for s in scores):
                continue
            plan.compute_names(epic_plan)
        if error is None:
            needed.update(c.symbol for c in epic_plan.name or ())
    return needed


def match_universe(
    plan: MatchingPlan,
    histories: Mapping[str, CapitalHistory],
    bars_by_symbol: Mapping[str, Sequence[AlpacaBar]],
    sessions: Sequence[Session],
    *,
    run_id: str,
    produced_at: datetime,
) -> list[InstrumentMapping]:
    """Score every candidate, classify every epic and resolve symbol conflicts.

    Name candidates are scored only when no identifier candidate passed the price check, so that
    a near-identical sibling (e.g. a bond-ETF ladder) cannot override a close identifier match.
    """
    locator = SessionLocator(sessions)
    records: list[InstrumentMapping] = []
    for epic, epic_plan in plan.epics.items():
        history = histories.get(epic)
        error = _history_error(history) if epic_plan.has_candidates else None
        scores = _score_all(
            epic_plan.identifier,
            history or CapitalHistory(),
            error,
            bars_by_symbol,
            locator,
            len(sessions),
            plan.thresholds,
        )
        if not any(s.price_ok for s in scores):
            names = plan.compute_names(epic_plan)
            if names:
                scores += _score_all(
                    names,
                    history or CapitalHistory(),
                    error,
                    bars_by_symbol,
                    locator,
                    len(sessions),
                    plan.thresholds,
                )
        records.append(
            classify(
                epic_plan.instrument,
                scores,
                error if scores else None,
                run_id=run_id,
                updated_at=produced_at,
            )
        )
    return resolve_symbol_conflicts(records)
