"""The reference-window fixture format round-trips every input of the pipeline."""

from pathlib import Path

from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.domain.matching.models import CapitalHistory, CapitalInstrument
from scripts.reference_window_io import ReferenceWindow, read_reference, write_reference
from tests.world import build_world


def test_round_trip(tmp_path: Path) -> None:
    world = build_world(3)
    histories = dict(world.collector.histories)
    histories["BIL"] = CapitalHistory.missing("Capital.com has no HOUR price history (HTTP 404)")
    original = ReferenceWindow(
        meta={"price_window_end": "2026-10-08T06:00:00+00:00", "thresholds": {}},
        sessions=world.alpaca.sessions,
        universe=[
            *world.collector.catalog,
            CapitalInstrument("NOHOURS", None, None, "SHARES", Source.SWEEP),
        ],
        assets=world.alpaca.assets,
        histories=histories,
        bars=world.alpaca.bars,
    )
    write_reference(tmp_path, original)
    loaded = read_reference(tmp_path)
    assert loaded.meta == original.meta
    assert loaded.sessions == original.sessions
    assert loaded.universe == original.universe
    assert loaded.assets == original.assets
    assert loaded.histories == original.histories
    assert loaded.bars == original.bars
