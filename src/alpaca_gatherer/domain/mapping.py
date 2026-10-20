"""Instrument mapping records: one per Capital.com epic.

>>> m = InstrumentMapping.matched(
...     capital_epic="BRKB", alpaca_symbol="BRK.B", match_type=MatchType.ALIAS,
...     run_id="r1", updated_at=datetime(2026, 10, 8, tzinfo=UTC),
... )
>>> m.status, m.alpaca_symbol
(<MatchStatus.MATCHED: 'matched'>, 'BRK.B')
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

__all__ = [
    "AMBIGUOUS_REASONS",
    "UNMATCHED_REASONS",
    "Candidate",
    "CandidateKind",
    "FailedCheck",
    "Horizon",
    "InstrumentMapping",
    "InvalidMapping",
    "MatchStatus",
    "MatchType",
    "Reason",
    "ReasonCode",
    "Source",
]


class MatchStatus(StrEnum):
    """Outcome of matching one epic."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


class MatchType(StrEnum):
    """How a matched epic reached its symbol (``alias`` covers identifier aliases and names)."""

    EXACT = "exact"
    ALIAS = "alias"


class CandidateKind(StrEnum):
    """How a candidate symbol was generated."""

    EXACT = "exact"
    ALIAS = "alias"
    NAME = "name"


class FailedCheck(StrEnum):
    """The check a candidate failed."""

    DATA = "data"
    PRICE = "price"
    BEHAVIOR = "behavior"
    TRADABILITY = "tradability"


class Horizon(StrEnum):
    """Return horizon that decided the behavior check."""

    HOURLY = "hourly"
    SESSION = "session"


class Source(StrEnum):
    """How an epic was discovered."""

    CATALOG = "catalog"
    SWEEP = "sweep"


class ReasonCode(StrEnum):
    """Reason categories for ambiguous and unmatched records."""

    MULTIPLE_CANDIDATES = "multiple_candidates"
    NAME_ONLY_WITH_UNCHECKED_IDENTIFIER = "name_only_with_unchecked_identifier"
    SYMBOL_CONFLICT = "symbol_conflict"
    NOT_LISTED_ON_ALPACA = "not_listed_on_alpaca"
    NOT_TRADABLE = "not_tradable"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED_PRICE_CHECK = "failed_price_check"
    FAILED_BEHAVIOR_CHECK = "failed_behavior_check"


AMBIGUOUS_REASONS = frozenset(
    {
        ReasonCode.MULTIPLE_CANDIDATES,
        ReasonCode.NAME_ONLY_WITH_UNCHECKED_IDENTIFIER,
        ReasonCode.SYMBOL_CONFLICT,
    }
)
UNMATCHED_REASONS = frozenset(
    {
        ReasonCode.NOT_LISTED_ON_ALPACA,
        ReasonCode.NOT_TRADABLE,
        ReasonCode.INSUFFICIENT_DATA,
        ReasonCode.FAILED_PRICE_CHECK,
        ReasonCode.FAILED_BEHAVIOR_CHECK,
    }
)


class InvalidMapping(ValueError):
    """A mapping record violates one of the status invariants."""


@dataclass(frozen=True, slots=True)
class Reason:
    """Reason category plus a human-readable detail."""

    code: ReasonCode
    detail: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """One Alpaca symbol examined for an epic, with its scores."""

    alpaca_symbol: str
    kind: CandidateKind
    tradable: bool
    active: bool
    passed: bool
    aligned_bars: int | None = None
    price_diff_pct: float | None = None
    direction_agreement: float | None = None
    return_correlation: float | None = None
    horizon: Horizon | None = None
    failed_check: FailedCheck | None = None


@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    """The stored mapping of one Capital.com epic.

    Invariants (checked on construction):

    * ``status = matched`` ⇒ ``alpaca_symbol`` and ``match_type`` are set and ``reason`` is null;
    * otherwise ``alpaca_symbol`` and ``match_type`` are null and ``reason`` is set, with a code
      allowed for that status.
    """

    capital_epic: str
    status: MatchStatus
    run_id: str
    updated_at: datetime
    alpaca_symbol: str | None = None
    match_type: MatchType | None = None
    reason: Reason | None = None
    capital_symbol: str | None = None
    capital_name: str | None = None
    source: Source = Source.CATALOG
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)
    price_diff_pct: float | None = None
    direction_agreement: float | None = None
    return_correlation: float | None = None
    horizon: Horizon | None = None

    def __post_init__(self) -> None:
        if not self.capital_epic:
            raise InvalidMapping("capital_epic must not be empty")
        if self.status is MatchStatus.MATCHED:
            if not self.alpaca_symbol or self.match_type is None:
                raise InvalidMapping("a matched record needs alpaca_symbol and match_type")
            if self.reason is not None:
                raise InvalidMapping("a matched record has no reason")
            return
        if self.alpaca_symbol is not None or self.match_type is not None:
            raise InvalidMapping(f"a {self.status} record has no alpaca_symbol or match_type")
        if self.reason is None:
            raise InvalidMapping(f"a {self.status} record needs a reason")
        allowed = AMBIGUOUS_REASONS if self.status is MatchStatus.AMBIGUOUS else UNMATCHED_REASONS
        if self.reason.code not in allowed:
            raise InvalidMapping(f"reason {self.reason.code} is not allowed for {self.status}")

    @classmethod
    def matched(
        cls,
        *,
        capital_epic: str,
        alpaca_symbol: str,
        match_type: MatchType,
        run_id: str,
        updated_at: datetime,
    ) -> InstrumentMapping:
        """Build a minimal matched record (mostly useful in tests and examples)."""
        return cls(
            capital_epic=capital_epic,
            status=MatchStatus.MATCHED,
            alpaca_symbol=alpaca_symbol,
            match_type=match_type,
            run_id=run_id,
            updated_at=updated_at.astimezone(UTC),
        )
