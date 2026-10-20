"""Ports: the interfaces use cases depend on. Adapters in ``infrastructure`` implement them.

Every port is a ``typing.Protocol``, so in-memory fakes satisfy them structurally in unit tests.
"""

import builtins
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Protocol

from alpaca_gatherer.domain.credentials import EncryptedCredentials, PlainCredentials
from alpaca_gatherer.domain.mapping import InstrumentMapping
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalHistory,
    CapitalInstrument,
    Session,
)
from alpaca_gatherer.domain.runs import Run
from alpaca_gatherer.domain.scheduling.definitions import CronValidator, ScheduleDefinition
from alpaca_gatherer.domain.thresholds import Feed

__all__ = [
    "AlpacaMarketPort",
    "CapitalCatalogPort",
    "Clock",
    "CredentialRepository",
    "CronValidator",
    "JobCallback",
    "JobScheduler",
    "MappingRepository",
    "RunRepository",
    "ScheduleRepository",
    "SecretCipher",
]

type JobCallback = Callable[[], Awaitable[None]]


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""
        ...


class MappingRepository(Protocol):
    """Live mapping reads, staging writes and the atomic swap."""

    async def find_by_epic(self, capital_epic: str) -> InstrumentMapping | None:
        """Return the record for an epic, whatever its status."""
        ...

    async def find_matched_by_symbol(self, alpaca_symbol: str) -> InstrumentMapping | None:
        """Return the matched record whose ``alpaca_symbol`` is the given symbol."""
        ...

    async def has_snapshot(self) -> bool:
        """True if a mapping snapshot exists (the live collection is present and not empty)."""
        ...

    async def write_staging(self, run_id: str, records: Sequence[InstrumentMapping]) -> None:
        """Write a full snapshot into the run's staging collection."""
        ...

    async def swap(self, run_id: str) -> None:
        """Atomically replace the live mapping with the run's staging collection."""
        ...

    async def drop_staging(self, run_id: str) -> None:
        """Drop the run's staging collection if it exists."""
        ...

    async def drop_all_staging(self) -> list[str]:
        """Drop every leftover staging collection; return their names."""
        ...


class RunRepository(Protocol):
    """Run documents, the single-run lock and history retention."""

    async def insert_running(self, run: Run) -> None:
        """Insert a running run; raise ``RunInProgress`` if another run is running."""
        ...

    async def insert_terminal(self, run: Run) -> None:
        """Insert a run that is already terminal (a recorded scheduled skip)."""
        ...

    async def finish(self, run: Run) -> None:
        """Store the terminal state of a run that was running."""
        ...

    async def get(self, run_id: str) -> Run | None:
        """Return one run."""
        ...

    async def list(self, limit: int, offset: int) -> builtins.list[Run]:
        """Return a page of runs, newest first."""
        ...

    async def count(self) -> int:
        """Return the number of retained runs."""
        ...

    async def active(self) -> Run | None:
        """Return the running run, if any."""
        ...

    async def latest_succeeded(self) -> Run | None:
        """Return the newest succeeded run."""
        ...

    async def mark_running_as_interrupted(self, now: datetime) -> builtins.list[str]:
        """Fail every running run as ``interrupted_by_restart``; return their ids."""
        ...

    async def prune(self, limit: int, skip_limit: int = 20) -> int:
        """Apply the retention policy; return the number of deleted runs."""
        ...


class ScheduleRepository(Protocol):
    """The single persisted schedule."""

    async def get(self) -> ScheduleDefinition | None:
        """Return the stored schedule, if any."""
        ...

    async def put(self, definition: ScheduleDefinition, updated_at: datetime) -> None:
        """Replace the stored schedule."""
        ...

    async def delete(self) -> None:
        """Remove the stored schedule (no error if there is none)."""
        ...


class CredentialRepository(Protocol):
    """The single stored (encrypted) Alpaca credential pair."""

    async def insert(self, credentials: EncryptedCredentials) -> None:
        """Store credentials; raise ``CredentialsExist`` if some are stored already."""
        ...

    async def update(self, api_key_enc: str, api_secret_enc: str, updated_at: datetime) -> None:
        """Replace stored credentials; raise ``CredentialsNotFound`` if none are stored."""
        ...

    async def get(self) -> EncryptedCredentials | None:
        """Return the stored credentials, if any."""
        ...


class SecretCipher(Protocol):
    """Symmetric encryption of credential values."""

    def encrypt(self, plain: str) -> str:
        """Return the ciphertext of ``plain``."""
        ...

    def decrypt(self, token: str) -> str:
        """Return the plain text; raise ``CredentialsUndecryptable`` on a wrong key or token."""
        ...


class JobScheduler(CronValidator, Protocol):
    """The in-process scheduler holding at most one matching job."""

    def replace_job(self, definition: ScheduleDefinition, callback: JobCallback) -> None:
        """Create or replace the single job."""
        ...

    def remove_job(self) -> None:
        """Remove the job if it exists."""
        ...

    def next_fire_time(self, definition: ScheduleDefinition, now: datetime) -> datetime | None:
        """Return when ``definition`` next fires after ``now`` (UTC), or ``None`` if never."""
        ...

    def start(self) -> None:
        """Start firing jobs."""
        ...

    def shutdown(self) -> None:
        """Stop firing jobs."""
        ...


class CapitalCatalogPort(Protocol):
    """Capital.com data obtained through the collector."""

    async def list_catalog_markets(self) -> list[CapitalInstrument]:
        """Return every market of the US share catalogs (source ``catalog``)."""
        ...

    async def lookup_markets(self, epics: Sequence[str]) -> list[CapitalInstrument]:
        """Return the markets that exist among ``epics`` (source ``sweep``)."""
        ...

    async def hourly_history(self, epic: str, start: datetime, end: datetime) -> CapitalHistory:
        """Return hourly bars of ``epic`` in ``[start, end]``, or why there are none."""
        ...

    async def aclose(self) -> None:
        """Release the underlying client."""
        ...


class AlpacaMarketPort(Protocol):
    """Alpaca assets, calendar and bars."""

    async def list_assets(self, credentials: PlainCredentials) -> list[AlpacaAsset]:
        """Return every ``us_equity`` asset, all statuses."""
        ...

    async def calendar(
        self, credentials: PlainCredentials, start: date, end: date
    ) -> list[Session]:
        """Return the regular sessions between two dates (inclusive), oldest first."""
        ...

    async def hourly_bars(
        self,
        credentials: PlainCredentials,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
        feed: Feed,
    ) -> Mapping[str, list[AlpacaBar]]:
        """Return raw hourly bars per symbol; symbols without bars are absent."""
        ...

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        ...
