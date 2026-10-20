"""In-memory fakes of every application port, for unit tests (no I/O)."""

import asyncio
import builtins
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from alpaca_gatherer.application.ports import JobCallback
from alpaca_gatherer.domain.credentials import EncryptedCredentials, PlainCredentials
from alpaca_gatherer.domain.errors import (
    CredentialsExist,
    CredentialsNotFound,
    CredentialsUndecryptable,
    RunInProgress,
)
from alpaca_gatherer.domain.mapping import InstrumentMapping, MatchStatus
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalHistory,
    CapitalInstrument,
    Session,
)
from alpaca_gatherer.domain.runs import (
    Run,
    RunError,
    RunErrorCode,
    RunStatus,
    select_runs_to_prune,
)
from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
    ScheduleDefinition,
)
from alpaca_gatherer.domain.thresholds import Feed


class FrozenClock:
    """A clock that only moves when told to."""

    def __init__(self, now: datetime | None = None) -> None:
        self.current = now or datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class InMemoryMappingRepository:
    """Live mapping plus staging snapshots kept in dictionaries."""

    def __init__(self, records: Sequence[InstrumentMapping] = ()) -> None:
        self.live: dict[str, InstrumentMapping] | None = (
            {r.capital_epic: r for r in records} if records else None
        )
        self.staging: dict[str, list[InstrumentMapping]] = {}
        self.swapped: list[str] = []

    async def find_by_epic(self, capital_epic: str) -> InstrumentMapping | None:
        return (self.live or {}).get(capital_epic)

    async def find_matched_by_symbol(self, alpaca_symbol: str) -> InstrumentMapping | None:
        for record in (self.live or {}).values():
            if record.status is MatchStatus.MATCHED and record.alpaca_symbol == alpaca_symbol:
                return record
        return None

    async def has_snapshot(self) -> bool:
        return bool(self.live)

    async def write_staging(self, run_id: str, records: Sequence[InstrumentMapping]) -> None:
        self.staging[run_id] = list(records)

    async def swap(self, run_id: str) -> None:
        self.live = {r.capital_epic: r for r in self.staging.pop(run_id)}
        self.swapped.append(run_id)

    async def drop_staging(self, run_id: str) -> None:
        self.staging.pop(run_id, None)

    async def drop_all_staging(self) -> list[str]:
        names = [f"staging_{run_id}" for run_id in self.staging]
        self.staging.clear()
        return names


class InMemoryRunRepository:
    """Run documents with the same single-running-run rule as the unique index."""

    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}

    async def insert_running(self, run: Run) -> None:
        active = await self.active()
        if active is not None:
            raise RunInProgress(active.run_id)
        self.runs[run.run_id] = run

    async def insert_terminal(self, run: Run) -> None:
        self.runs[run.run_id] = run

    async def finish(self, run: Run) -> None:
        self.runs[run.run_id] = run

    async def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    async def list(self, limit: int, offset: int) -> builtins.list[Run]:
        ordered = sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)
        return ordered[offset : offset + limit]

    async def count(self) -> int:
        return len(self.runs)

    async def active(self) -> Run | None:
        return next((r for r in self.runs.values() if r.status is RunStatus.RUNNING), None)

    async def latest_succeeded(self) -> Run | None:
        done = [r for r in self.runs.values() if r.status is RunStatus.SUCCEEDED]
        return max(done, key=lambda r: r.started_at, default=None)

    async def mark_running_as_interrupted(self, now: datetime) -> builtins.list[str]:
        ids = []
        for run in list(self.runs.values()):
            if run.status is RunStatus.RUNNING:
                error = RunError(
                    RunErrorCode.INTERRUPTED_BY_RESTART, "interrupted by service restart"
                )
                self.runs[run.run_id] = run.fail(now, error)
                ids.append(run.run_id)
        return ids

    async def prune(self, limit: int, skip_limit: int = 20) -> int:
        doomed = select_runs_to_prune(list(self.runs.values()), limit, skip_limit)
        for run_id in doomed:
            del self.runs[run_id]
        return len(doomed)


class InMemoryScheduleRepository:
    """The single schedule document."""

    def __init__(self, definition: ScheduleDefinition | None = None) -> None:
        self.definition = definition
        self.updated_at: datetime | None = None
        self.writes = 0

    async def get(self) -> ScheduleDefinition | None:
        return self.definition

    async def put(self, definition: ScheduleDefinition, updated_at: datetime) -> None:
        self.definition = definition
        self.updated_at = updated_at
        self.writes += 1

    async def delete(self) -> None:
        self.definition = None
        self.writes += 1


class InMemoryCredentialRepository:
    """The single credential document."""

    def __init__(self, stored: EncryptedCredentials | None = None) -> None:
        self.stored = stored

    async def insert(self, credentials: EncryptedCredentials) -> None:
        if self.stored is not None:
            raise CredentialsExist()
        self.stored = credentials

    async def update(self, api_key_enc: str, api_secret_enc: str, updated_at: datetime) -> None:
        if self.stored is None:
            raise CredentialsNotFound()
        self.stored = replace(
            self.stored,
            api_key_enc=api_key_enc,
            api_secret_enc=api_secret_enc,
            updated_at=updated_at,
        )

    async def get(self) -> EncryptedCredentials | None:
        return self.stored


class ReversingCipher:
    """A toy reversible cipher; tokens it did not produce cannot be decrypted."""

    prefix = "enc:"

    def encrypt(self, plain: str) -> str:
        return self.prefix + plain[::-1]

    def decrypt(self, token: str) -> str:
        if not token.startswith(self.prefix):
            raise CredentialsUndecryptable()
        return token.removeprefix(self.prefix)[::-1]


class FakeJobScheduler:
    """Records the job instead of scheduling it; next fire times are simple and predictable."""

    def __init__(self) -> None:
        self.job: tuple[ScheduleDefinition, JobCallback] | None = None
        self.started = False
        self.stopped = False

    def validate_cron(self, expression: str) -> None:
        fields = expression.split()
        if len(fields) != 5 or any(f.isdigit() and int(f) > 59 for f in fields[:1]):
            raise ValueError("bad cron")

    def replace_job(self, definition: ScheduleDefinition, callback: JobCallback) -> None:
        self.job = (definition, callback)

    def remove_job(self) -> None:
        self.job = None

    def next_fire_time(self, definition: ScheduleDefinition, now: datetime) -> datetime | None:
        match definition:
            case OneTimeSchedule(date=when):
                return when if when > now else None
            case CronSchedule():
                return now + timedelta(minutes=5)
            case RecurringSchedule():
                return now + timedelta(days=1)

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True

    async def fire(self) -> None:
        assert self.job is not None
        await self.job[1]()


@dataclass
class FakeCollector:
    """Collector port backed by in-memory data; ``fail_with`` raises from every call."""

    catalog: list[CapitalInstrument] = field(default_factory=list)
    markets: dict[str, CapitalInstrument] = field(default_factory=dict)
    histories: dict[str, CapitalHistory] = field(default_factory=dict)
    fail_with: Exception | None = None
    delay: float = 0.0
    gate: asyncio.Event | None = None
    closed: bool = False

    async def _maybe_fail(self) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None:
            raise self.fail_with

    async def list_catalog_markets(self) -> list[CapitalInstrument]:
        await self._maybe_fail()
        return list(self.catalog)

    async def lookup_markets(self, epics: Sequence[str]) -> list[CapitalInstrument]:
        await self._maybe_fail()
        return [self.markets[e] for e in epics if e in self.markets]

    async def hourly_history(self, epic: str, start: datetime, end: datetime) -> CapitalHistory:
        await self._maybe_fail()
        history = self.histories.get(epic)
        if history is None:
            return CapitalHistory.missing("Capital.com returned no bars in window")
        bars = tuple(b for b in history.bars if start <= b.ts <= end)
        return replace(history, bars=bars)

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class FakeAlpaca:
    """Alpaca port backed by in-memory data; records the credentials it was given."""

    assets: list[AlpacaAsset] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    bars: dict[str, list[AlpacaBar]] = field(default_factory=dict)
    fail_with: Exception | None = None
    seen_credentials: list[PlainCredentials] = field(default_factory=list)
    closed: bool = False

    def _use(self, credentials: PlainCredentials) -> None:
        self.seen_credentials.append(credentials)
        if self.fail_with is not None:
            raise self.fail_with

    async def list_assets(self, credentials: PlainCredentials) -> list[AlpacaAsset]:
        self._use(credentials)
        return list(self.assets)

    async def calendar(
        self, credentials: PlainCredentials, start: date, end: date
    ) -> list[Session]:
        self._use(credentials)
        return [s for s in self.sessions if start <= s.open.date() <= end]

    async def hourly_bars(
        self,
        credentials: PlainCredentials,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
        feed: Feed,
    ) -> Mapping[str, list[AlpacaBar]]:
        self._use(credentials)
        return {
            s: [b for b in self.bars[s] if start <= b.ts <= end] for s in symbols if s in self.bars
        }

    async def aclose(self) -> None:
        self.closed = True
