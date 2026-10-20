"""FR-005 guard: nothing in the service, its config or its tests refers to the prototype."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("alpaca" + "Matcher", "match_" + "instruments", "alpaca" + "-keys")
SCANNED = ("src", "config", "tests", "scripts")


def test_no_file_refers_to_the_prototype() -> None:
    offenders: list[str] = []
    for top in SCANNED:
        for path in (ROOT / top).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [f"{path.relative_to(ROOT)}: {word}" for word in FORBIDDEN if word in text]
    assert not offenders, "prototype references found:\n" + "\n".join(offenders)
