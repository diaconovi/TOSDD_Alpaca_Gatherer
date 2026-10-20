"""Golden test (SC-006): the matching domain over a recorded window agrees with the baseline.

Compares ``status``, ``match_type`` and ``alpaca_symbol`` per epic over the epics present on both
sides; at least 99 % must agree. Epics present on only one side (universe churn between the two
recordings) are reported but do not fail the test.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpaca_gatherer.domain.matching.pipeline import (
    build_plan,
    match_universe,
    name_candidates_needed,
)
from alpaca_gatherer.domain.thresholds import Thresholds
from scripts.reference_window_io import read_reference

FIXTURE = Path(__file__).parents[1] / "fixtures" / "reference_window"
REQUIRED_AGREEMENT = 0.99


def test_matching_agrees_with_reference_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    expected_path = FIXTURE / "expected_mapping.json"
    if not expected_path.exists():
        pytest.skip(f"reference window not recorded yet ({FIXTURE}); see its README.md")
    ref = read_reference(FIXTURE)
    expected: dict[str, dict[str, str | None]] = json.loads(expected_path.read_text())
    thresholds = Thresholds.defaults()
    assert ref.meta["thresholds"] == thresholds.as_dict(), "fixture recorded with other thresholds"

    plan = build_plan(ref.universe, ref.assets, thresholds)
    # Same steps as a run; symbols without recorded bars had none in the window.
    name_candidates_needed(plan, ref.histories, ref.bars, ref.sessions)
    records = match_universe(
        plan,
        ref.histories,
        ref.bars,
        ref.sessions,
        run_id="golden",
        produced_at=datetime.now(UTC),
    )
    actual = {
        r.capital_epic: (
            r.status.value,
            r.match_type.value if r.match_type else None,
            r.alpaca_symbol,
        )
        for r in records
    }
    wanted = {
        epic: (e["status"], e["match_type"], e["alpaca_symbol"]) for epic, e in expected.items()
    }
    common = sorted(actual.keys() & wanted.keys())
    differences = [
        f"{epic}: service {actual[epic]} vs baseline {wanted[epic]}"
        for epic in common
        if actual[epic] != wanted[epic]
    ]
    only_service = sorted(actual.keys() - wanted.keys())
    only_baseline = sorted(wanted.keys() - actual.keys())
    with capsys.disabled():
        print(
            f"\ngolden: {len(common)} common epics, {len(differences)} differ; "
            f"universe churn: {len(only_service)} only in the service, "
            f"{len(only_baseline)} only in the baseline"
        )
    assert common, "no epic in common between the recorded universe and the baseline"
    agreement = 1 - len(differences) / len(common)
    assert agreement >= REQUIRED_AGREEMENT, (
        f"agreement {agreement:.4f} < {REQUIRED_AGREEMENT}; differences:\n" + "\n".join(differences)
    )
