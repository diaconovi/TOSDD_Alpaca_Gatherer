"""The Capital.com US share universe: catalog union plus an epic sweep.

The collector's four US catalogs are each capped at 500 entries, so the universe also includes
epics found by looking up spellings derived from active Alpaca symbols. A swept market is kept only
if it is a USD-priced share trading the US cash session.

>>> hours = OpeningHours("UTC", {"mon": ("13:30 - 20:00",)})
>>> trades_us_session(hours)
True
"""

from collections.abc import Iterable, Sequence

from alpaca_gatherer.domain.matching.models import AlpacaAsset, CapitalInstrument, OpeningHours
from alpaca_gatherer.domain.matching.normalize import sweep_epics

__all__ = [
    "SHARES",
    "US_CLOSE_TIMES",
    "build_universe",
    "keep_swept",
    "sweep_candidates",
    "trades_us_session",
]

SHARES = "SHARES"
US_CLOSE_TIMES = frozenset({"20:00", "21:00", "00:00"})
"""Weekday interval ends that mean "closes with the US cash session" (or trades 24 h)."""
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")


def trades_us_session(hours: OpeningHours | None) -> bool:
    """True if UTC weekday hours end at the US cash close (20:00 or 21:00 UTC) or run 24 h."""
    if hours is None or hours.zone != "UTC":
        return False
    for day in _WEEKDAYS:
        for interval in hours.days.get(day, ()):
            if interval.split("-")[-1].strip() in US_CLOSE_TIMES:
                return True
    return False


def keep_swept(instrument: CapitalInstrument) -> bool:
    """A swept market is kept if it is a USD share trading the US cash session."""
    return (
        instrument.instrument_type == SHARES
        and instrument.currency == "USD"
        and trades_us_session(instrument.opening_hours)
    )


def sweep_candidates(assets: Iterable[AlpacaAsset], known_epics: Iterable[str]) -> list[str]:
    """Epics to look up in the sweep: spellings of active Alpaca symbols not already known."""
    known = set(known_epics)
    return sorted(sweep_epics(a.symbol for a in assets if a.active) - known)


def build_universe(
    catalog: Sequence[CapitalInstrument], swept: Sequence[CapitalInstrument]
) -> list[CapitalInstrument]:
    """Merge the catalog shares and the kept swept markets; catalog entries take precedence.

    The result is sorted by epic and has one instrument per epic.
    """
    found: dict[str, CapitalInstrument] = {}
    for instrument in catalog:
        if instrument.instrument_type == SHARES:
            found.setdefault(instrument.epic, instrument)
    for instrument in swept:
        if instrument.epic not in found and keep_swept(instrument):
            found[instrument.epic] = instrument
    return [found[epic] for epic in sorted(found)]
