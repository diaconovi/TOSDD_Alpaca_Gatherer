"""Response models of ``GET /api/v1/mappings`` (``Mapping`` in contracts/openapi.yaml)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alpaca_gatherer.domain.mapping import Candidate, InstrumentMapping

__all__ = ["CandidateResponse", "MappingResponse", "ReasonResponse"]


class ReasonResponse(BaseModel):
    """Reason category and human-readable detail."""

    code: str
    detail: str


class CandidateResponse(BaseModel):
    """A candidate symbol with its quality measures."""

    alpaca_symbol: str
    kind: Literal["exact", "alias", "name"]
    tradable: bool
    price_diff_pct: float | None
    direction_agreement: float | None
    return_correlation: float | None
    passed: bool

    @classmethod
    def of(cls, c: Candidate) -> CandidateResponse:
        """Build from a domain candidate."""
        return cls(
            alpaca_symbol=c.alpaca_symbol,
            kind=c.kind.value,
            tradable=c.tradable,
            price_diff_pct=c.price_diff_pct,
            direction_agreement=c.direction_agreement,
            return_correlation=c.return_correlation,
            passed=c.passed,
        )


class MappingResponse(BaseModel):
    """The stored mapping of one epic."""

    capital_epic: str
    status: Literal["matched", "ambiguous", "unmatched"]
    match_type: Literal["exact", "alias"] | None
    alpaca_symbol: str | None
    candidates: list[CandidateResponse]
    price_diff_pct: float | None
    direction_agreement: float | None
    return_correlation: float | None
    reason: ReasonResponse | None
    run_id: str
    updated_at: datetime

    @classmethod
    def of(cls, m: InstrumentMapping) -> MappingResponse:
        """Build from a domain mapping record."""
        return cls(
            capital_epic=m.capital_epic,
            status=m.status.value,
            match_type=m.match_type.value if m.match_type else None,
            alpaca_symbol=m.alpaca_symbol,
            candidates=[CandidateResponse.of(c) for c in m.candidates],
            price_diff_pct=m.price_diff_pct,
            direction_agreement=m.direction_agreement,
            return_correlation=m.return_correlation,
            reason=ReasonResponse(code=m.reason.code.value, detail=m.reason.detail)
            if m.reason
            else None,
            run_id=m.run_id,
            updated_at=m.updated_at,
        )
