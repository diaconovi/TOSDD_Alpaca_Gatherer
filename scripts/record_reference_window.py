"""Record the inputs of one matching window for the golden test (SC-006).

Uses this service's own ``CollectorGateway`` and ``AlpacaGateway`` and the same gathering code as a
run, so the fixture holds exactly what a run would have compared.

Usage::

    ALPACA_API_KEY=… ALPACA_API_SECRET=… \\
        uv run python -m scripts.record_reference_window --end 2026-10-08T06:00:00+00:00

Settings: ``COLLECTOR_URL`` (default ``http://localhost:8001``), ``ALPACA_TRADING_URL``,
``ALPACA_DATA_URL`` and ``THRESHOLDS_FILE`` (defaults as in ``.env.example``). The credentials are
read from the environment only and are never printed.
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from to_collector_client import CollectorClient

from alpaca_gatherer.application.runs.market_data import gather_market_data
from alpaca_gatherer.config import load_thresholds
from alpaca_gatherer.domain.credentials import PlainCredentials
from alpaca_gatherer.infrastructure.clients.alpaca import AlpacaGateway
from alpaca_gatherer.infrastructure.clients.collector import CollectorGateway
from alpaca_gatherer.logging_setup import configure_logging, register_secret
from scripts.reference_window_io import ReferenceWindow, write_reference

DEFAULT_OUT = Path("tests/fixtures/reference_window")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--end", required=True, help="window end, ISO 8601 with offset")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixture directory")
    return parser.parse_args()


async def _record(end: datetime, out: Path) -> None:
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        sys.exit("set ALPACA_API_KEY and ALPACA_API_SECRET in the environment")
    register_secret(key)
    register_secret(secret)
    thresholds = load_thresholds(Path(os.environ.get("THRESHOLDS_FILE", "config/thresholds.yaml")))
    url = urlsplit(os.environ.get("COLLECTOR_URL", "http://localhost:8001"))
    scheme: Literal["http", "https"] = "https" if url.scheme == "https" else "http"
    collector = CollectorGateway(
        CollectorClient(url.hostname or "localhost", url.port or 80, scheme=scheme)
    )
    alpaca = AlpacaGateway(
        os.environ.get("ALPACA_TRADING_URL", "https://paper-api.alpaca.markets"),
        os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets"),
    )
    try:
        data = await gather_market_data(
            credentials=PlainCredentials(key, secret),
            collector=collector,
            alpaca=alpaca,
            thresholds=thresholds,
            window_end=end,
        )
    finally:
        await collector.aclose()
        await alpaca.aclose()
    meta = {
        "price_window_end": end.isoformat(),
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window": {
            "start": data.window.start.isoformat(),
            "end": data.window.end.isoformat(),
            "sessions": data.window.sessions,
        },
        "thresholds": thresholds.as_dict(),
        "counts": {
            "universe": len(data.universe),
            "assets": len(data.assets),
            "capital_histories": len(data.histories),
            "alpaca_symbols_with_bars": len(data.bars),
        },
    }
    write_reference(
        out,
        ReferenceWindow(
            meta=meta,
            sessions=data.sessions,
            universe=data.universe,
            assets=data.assets,
            histories=data.histories,
            bars=data.bars,
        ),
    )
    logging.getLogger("record").info("wrote %s: %s", out, meta["counts"])


def main() -> None:
    """Entry point."""
    args = _parse_args()
    configure_logging("INFO", "UTC")
    end = datetime.fromisoformat(args.end)
    if end.tzinfo is None:
        sys.exit("--end must include a UTC offset")
    asyncio.run(_record(end.astimezone(UTC), args.out))


if __name__ == "__main__":
    main()
