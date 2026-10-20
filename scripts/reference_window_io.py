"""Read and write the reference-window fixtures (``tests/fixtures/reference_window``).

Large inputs are stored as gzip-compressed JSON so the fixture stays small enough to commit:

* ``meta.json``: window end, window, feed, thresholds, record time;
* ``sessions.json``: the sessions of the window, ``[open, close]`` in ISO 8601 UTC;
* ``universe.json``: the Capital.com US share universe;
* ``assets.json.gz``: every Alpaca ``us_equity`` asset as
  ``[symbol, name, exchange, active, tradable]``;
* ``capital_bars.json.gz``: per epic ``{"error": str | null, "bars": [[epoch_s, bid, ask], …]}``;
* ``alpaca_bars.json.gz``: per symbol ``[[epoch_s, close], …]``;
* ``expected_mapping.json``: the baseline classification per epic.
"""

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalBar,
    CapitalHistory,
    CapitalInstrument,
    OpeningHours,
    Session,
)

__all__ = ["ReferenceWindow", "read_reference", "write_reference"]


@dataclass(slots=True)
class ReferenceWindow:
    """Recorded inputs of one matching window."""

    meta: dict[str, Any]
    sessions: list[Session]
    universe: list[CapitalInstrument]
    assets: list[AlpacaAsset]
    histories: dict[str, CapitalHistory]
    bars: dict[str, list[AlpacaBar]]


def _ts(value: datetime) -> int:
    return int(value.timestamp())


def _dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _write_json(path: Path, data: object) -> None:
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
    else:
        path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:  # fixture JSON, typed by the caller
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))


def write_reference(directory: Path, ref: ReferenceWindow) -> None:
    """Write every fixture file of a reference window into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / "meta.json", ref.meta)
    _write_json(
        directory / "sessions.json",
        [[s.open.isoformat(), s.close.isoformat()] for s in ref.sessions],
    )
    _write_json(
        directory / "universe.json",
        [
            {
                "epic": i.epic,
                "symbol": i.symbol,
                "name": i.name,
                "instrument_type": i.instrument_type,
                "source": i.source.value,
                "currency": i.currency,
                "opening_hours": (
                    {"zone": i.opening_hours.zone, "days": dict(i.opening_hours.days)}
                    if i.opening_hours
                    else None
                ),
            }
            for i in ref.universe
        ],
    )
    _write_json(
        directory / "assets.json.gz",
        [[a.symbol, a.name, a.exchange, a.active, a.tradable] for a in ref.assets],
    )
    _write_json(
        directory / "capital_bars.json.gz",
        {
            epic: {"error": h.error, "bars": [[_ts(b.ts), b.bid, b.ask] for b in h.bars]}
            for epic, h in sorted(ref.histories.items())
        },
    )
    _write_json(
        directory / "alpaca_bars.json.gz",
        {s: [[_ts(b.ts), b.close] for b in bars] for s, bars in sorted(ref.bars.items())},
    )


def read_reference(directory: Path) -> ReferenceWindow:
    """Read a reference window written by ``write_reference``."""
    universe = [
        CapitalInstrument(
            epic=i["epic"],
            symbol=i["symbol"],
            name=i["name"],
            instrument_type=i["instrument_type"],
            source=Source(i["source"]),
            currency=i["currency"],
            opening_hours=(
                OpeningHours(
                    i["opening_hours"]["zone"],
                    {d: tuple(v) for d, v in i["opening_hours"]["days"].items()},
                )
                if i["opening_hours"]
                else None
            ),
        )
        for i in _read_json(directory / "universe.json")
    ]
    histories = {
        epic: CapitalHistory(
            tuple(CapitalBar(_dt(t), bid, ask) for t, bid, ask in h["bars"]), h["error"]
        )
        for epic, h in _read_json(directory / "capital_bars.json.gz").items()
    }
    return ReferenceWindow(
        meta=_read_json(directory / "meta.json"),
        sessions=[
            Session(datetime.fromisoformat(o), datetime.fromisoformat(c))
            for o, c in _read_json(directory / "sessions.json")
        ],
        universe=universe,
        assets=[AlpacaAsset(*row) for row in _read_json(directory / "assets.json.gz")],
        histories=histories,
        bars={
            s: [AlpacaBar(_dt(t), c) for t, c in rows]
            for s, rows in _read_json(directory / "alpaca_bars.json.gz").items()
        },
    )
