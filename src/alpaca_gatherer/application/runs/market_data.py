"""Gather every input of the matching process for one window.

Used by ``ExecuteRun`` and by the reference-window recorder, so both fetch exactly the same data:
Alpaca assets and calendar → window → Capital.com universe (catalogs + sweep) → candidate plan →
Capital.com hourly bars → Alpaca hourly bars (identifier candidates, then name candidates).
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from alpaca_gatherer.application.ports import AlpacaMarketPort, CapitalCatalogPort
from alpaca_gatherer.domain.credentials import PlainCredentials
from alpaca_gatherer.domain.errors import AlpacaUnavailable, CollectorIncompleteData
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalHistory,
    CapitalInstrument,
    Session,
)
from alpaca_gatherer.domain.matching.pipeline import (
    MatchingPlan,
    build_plan,
    name_candidates_needed,
)
from alpaca_gatherer.domain.matching.universe import build_universe, sweep_candidates
from alpaca_gatherer.domain.matching.window import calendar_range, query_range, select_sessions
from alpaca_gatherer.domain.runs import RunWindow
from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = ["MarketData", "gather_market_data"]

log = logging.getLogger(__name__)


@dataclass(slots=True)
class MarketData:
    """Everything ``match_universe`` needs, plus the inputs it was derived from."""

    assets: list[AlpacaAsset]
    sessions: list[Session]
    window: RunWindow
    universe: list[CapitalInstrument]
    plan: MatchingPlan
    histories: dict[str, CapitalHistory]
    bars: dict[str, list[AlpacaBar]]


async def gather_market_data(
    *,
    credentials: PlainCredentials,
    collector: CapitalCatalogPort,
    alpaca: AlpacaMarketPort,
    thresholds: Thresholds,
    window_end: datetime,
) -> MarketData:
    """Fetch and prepare the inputs of a run whose window ends at ``window_end``."""
    th = thresholds
    assets = await alpaca.list_assets(credentials)
    if not assets:
        raise AlpacaUnavailable("Alpaca returned no us_equity assets")
    log.info("%d Alpaca us_equity assets", len(assets))
    first_day, last_day = calendar_range(window_end, th.window.sessions)
    calendar = await alpaca.calendar(credentials, first_day, last_day)
    sessions = select_sessions(calendar, window_end, th.window.sessions, th.window.embargo_minutes)
    start, end = query_range(sessions)
    log.info("window %s to %s (%d sessions)", start, end, len(sessions))

    catalog = await collector.list_catalog_markets()
    swept = await collector.lookup_markets(sweep_candidates(assets, {i.epic for i in catalog}))
    universe = build_universe(catalog, swept)
    if not universe:
        raise CollectorIncompleteData("the collector returned no Capital.com US shares")
    log.info("universe: %d Capital.com US shares", len(universe))

    plan = await asyncio.to_thread(build_plan, universe, assets, th)
    histories = await _histories(collector, plan.epics_needing_history(), start, end)
    requested = plan.symbols()
    bars = await _bars(alpaca, credentials, requested, start, end, th)
    extra = await asyncio.to_thread(name_candidates_needed, plan, histories, bars, sessions)
    if extra - requested:
        bars.update(await _bars(alpaca, credentials, extra - requested, start, end, th))
    return MarketData(
        assets=assets,
        sessions=sessions,
        window=RunWindow(start, end, len(sessions)),
        universe=universe,
        plan=plan,
        histories=histories,
        bars=bars,
    )


async def _histories(
    collector: CapitalCatalogPort, epics: Sequence[str], start: datetime, end: datetime
) -> dict[str, CapitalHistory]:
    log.info("fetching Capital.com hourly bars for %d epics", len(epics))
    async with asyncio.TaskGroup() as group:
        tasks = {e: group.create_task(collector.hourly_history(e, start, end)) for e in epics}
    return {epic: task.result() for epic, task in tasks.items()}


async def _bars(
    alpaca: AlpacaMarketPort,
    credentials: PlainCredentials,
    symbols: set[str],
    start: datetime,
    end: datetime,
    thresholds: Thresholds,
) -> dict[str, list[AlpacaBar]]:
    log.info("fetching Alpaca hourly bars for %d symbols", len(symbols))
    return dict(
        await alpaca.hourly_bars(credentials, sorted(symbols), start, end, thresholds.window.feed)
    )
