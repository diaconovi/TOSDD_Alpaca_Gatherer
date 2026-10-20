"""MongoDB mapping repository: live reads, staging writes and the atomic swap (research R5).

A run writes its full snapshot into ``M_staging_<run_id>`` and then renames it onto ``M`` with
``dropTarget=True``, so a reader sees either the whole old snapshot or the whole new one.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from pymongo.errors import OperationFailure

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
from alpaca_gatherer.infrastructure.db.client import (
    Collections,
    Document,
    MongoCollection,
    MongoDatabase,
)
from alpaca_gatherer.infrastructure.db.indexes import create_mapping_indexes

__all__ = ["MongoMappingRepository", "from_document", "to_document"]

log = logging.getLogger(__name__)

_INSERT_BATCH = 1000
_QUERY_PLAN_KILLED = 175
"""A read that overlaps the swap's ``renameCollection`` is killed; repeating it reads the new
snapshot."""
_READ_ATTEMPTS = 3


def _opt[T](value: Any, kind: Callable[[Any], T]) -> T | None:
    return None if value is None else kind(value)


def _candidate_to_document(c: Candidate) -> Document:
    return {
        "alpaca_symbol": c.alpaca_symbol,
        "kind": c.kind.value,
        "tradable": c.tradable,
        "active": c.active,
        "passed": c.passed,
        "aligned_bars": c.aligned_bars,
        "price_diff_pct": c.price_diff_pct,
        "direction_agreement": c.direction_agreement,
        "return_correlation": c.return_correlation,
        "horizon": c.horizon.value if c.horizon else None,
        "failed_check": c.failed_check.value if c.failed_check else None,
    }


def _candidate_from_document(doc: Document) -> Candidate:
    return Candidate(
        alpaca_symbol=doc["alpaca_symbol"],
        kind=CandidateKind(doc["kind"]),
        tradable=bool(doc["tradable"]),
        active=bool(doc.get("active", True)),
        passed=bool(doc["passed"]),
        aligned_bars=doc.get("aligned_bars"),
        price_diff_pct=doc.get("price_diff_pct"),
        direction_agreement=doc.get("direction_agreement"),
        return_correlation=doc.get("return_correlation"),
        horizon=_opt(doc.get("horizon"), Horizon),
        failed_check=_opt(doc.get("failed_check"), FailedCheck),
    )


def to_document(m: InstrumentMapping) -> Document:
    """Convert a mapping record into its BSON document."""
    return {
        "capital_epic": m.capital_epic,
        "capital_symbol": m.capital_symbol,
        "capital_name": m.capital_name,
        "source": m.source.value,
        "status": m.status.value,
        "match_type": m.match_type.value if m.match_type else None,
        "alpaca_symbol": m.alpaca_symbol,
        "candidates": [_candidate_to_document(c) for c in m.candidates],
        "price_diff_pct": m.price_diff_pct,
        "direction_agreement": m.direction_agreement,
        "return_correlation": m.return_correlation,
        "horizon": m.horizon.value if m.horizon else None,
        "reason": {"code": m.reason.code.value, "detail": m.reason.detail} if m.reason else None,
        "run_id": m.run_id,
        "updated_at": m.updated_at,
    }


def from_document(doc: Document) -> InstrumentMapping:
    """Convert a BSON document back into a mapping record."""
    reason = doc.get("reason")
    return InstrumentMapping(
        capital_epic=doc["capital_epic"],
        capital_symbol=doc.get("capital_symbol"),
        capital_name=doc.get("capital_name"),
        source=Source(doc.get("source", Source.CATALOG.value)),
        status=MatchStatus(doc["status"]),
        match_type=_opt(doc.get("match_type"), MatchType),
        alpaca_symbol=doc.get("alpaca_symbol"),
        candidates=tuple(_candidate_from_document(c) for c in doc.get("candidates", [])),
        price_diff_pct=doc.get("price_diff_pct"),
        direction_agreement=doc.get("direction_agreement"),
        return_correlation=doc.get("return_correlation"),
        horizon=_opt(doc.get("horizon"), Horizon),
        reason=Reason(ReasonCode(reason["code"]), reason["detail"]) if reason else None,
        run_id=doc["run_id"],
        updated_at=doc["updated_at"],
    )


class MongoMappingRepository:
    """Implements ``MappingRepository`` on the collections named by ``Collections``."""

    def __init__(self, db: MongoDatabase, collections: Collections) -> None:
        self._db = db
        self._names = collections

    @property
    def _live(self) -> MongoCollection:
        return self._db[self._names.mapping]

    async def _find_one(
        self, query: Document, projection: Document | None = None
    ) -> Document | None:
        """``find_one`` on the live collection, retried when a swap kills the query plan."""
        for attempt in range(_READ_ATTEMPTS):
            try:
                return await self._live.find_one(query, projection=projection)
            except OperationFailure as exc:
                if exc.code != _QUERY_PLAN_KILLED or attempt == _READ_ATTEMPTS - 1:
                    raise
        return None  # pragma: no cover - the loop always returns or raises

    async def find_by_epic(self, capital_epic: str) -> InstrumentMapping | None:
        """Return the record for an epic, whatever its status."""
        doc = await self._find_one({"capital_epic": capital_epic})
        return from_document(doc) if doc else None

    async def find_matched_by_symbol(self, alpaca_symbol: str) -> InstrumentMapping | None:
        """Return the matched record for a symbol (ambiguous candidates are never returned)."""
        doc = await self._find_one(
            {"alpaca_symbol": alpaca_symbol, "status": MatchStatus.MATCHED.value}
        )
        return from_document(doc) if doc else None

    async def has_snapshot(self) -> bool:
        """True if the live collection exists and holds at least one record."""
        return await self._find_one({}, projection={"_id": 1}) is not None

    async def write_staging(self, run_id: str, records: Sequence[InstrumentMapping]) -> None:
        """Write the run's snapshot into a fresh staging collection with the mapping indexes."""
        staging = self._db[self._names.staging(run_id)]
        await staging.drop()
        await create_mapping_indexes(staging)
        docs = [to_document(r) for r in records]
        for start in range(0, len(docs), _INSERT_BATCH):
            await staging.insert_many(docs[start : start + _INSERT_BATCH], ordered=True)

    async def swap(self, run_id: str) -> None:
        """Atomically replace the live mapping with the run's staging collection."""
        staging = self._db[self._names.staging(run_id)]
        await staging.rename(self._names.mapping, dropTarget=True)
        log.info("mapping snapshot of run %s is now live", run_id)

    async def drop_staging(self, run_id: str) -> None:
        """Drop the run's staging collection, if any."""
        await self._db[self._names.staging(run_id)].drop()

    async def drop_all_staging(self) -> list[str]:
        """Drop every leftover staging collection of this mapping."""
        prefix = self._names.staging_prefix
        names = [n for n in await self._db.list_collection_names() if n.startswith(prefix)]
        for name in names:
            await self._db[name].drop()
        return names
