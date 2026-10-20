"""Convert a baseline ``mapping.csv`` into ``expected_mapping.json`` for the golden test.

The CSV has the columns ``epic, alpaca_symbol, status, price_diff_pct, direction_agreement,
return_correlation, reason`` with statuses ``matched_exact``, ``matched_alias``, ``ambiguous`` and
``unmatched``. Matched rows map to ``{status: matched, match_type: exact|alias}``; the reason code
of other rows is the text before the first ``:``.

Usage::

    uv run python scripts/convert_baseline.py path/to/mapping.csv
"""

import argparse
import csv
import json
from pathlib import Path

DEFAULT_OUT = Path("tests/fixtures/reference_window/expected_mapping.json")
MATCHED = {"matched_exact": "exact", "matched_alias": "alias"}
AMBIGUOUS_REASONS = {
    "several candidates pass": "multiple_candidates",
    "name match": "name_only_with_unchecked_identifier",
}


def _reason(status: str, text: str) -> str | None:
    if status == "ambiguous":
        return next(
            (code for prefix, code in AMBIGUOUS_REASONS.items() if text.startswith(prefix)),
            "multiple_candidates",
        )
    if status == "unmatched":
        return text.split(":", 1)[0].strip()
    return None


def convert(csv_path: Path) -> dict[str, dict[str, str | None]]:
    """Read the baseline CSV and return the expected classification per epic."""
    out: dict[str, dict[str, str | None]] = {}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = row["status"]
            match_type = MATCHED.get(raw)
            out[row["epic"]] = {
                "status": "matched" if match_type else raw,
                "match_type": match_type,
                "alpaca_symbol": (row["alpaca_symbol"] or None) if match_type else None,
                "reason": _reason(raw, row.get("reason") or ""),
            }
    return dict(sorted(out.items()))


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    expected = convert(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(expected)} epics to {args.out}")


if __name__ == "__main__":
    main()
