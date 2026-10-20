"""Threshold file loading and validation (research R9)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from alpaca_gatherer.config import ConfigError, load_thresholds
from alpaca_gatherer.domain.thresholds import Thresholds

VALID: dict[str, dict[str, Any]] = {
    "candidates": {"name_ratio": 0.9, "max_name_candidates": 3},
    "window": {"sessions": 20, "embargo_minutes": 20, "min_bars": 60, "feed": "sip"},
    "price": {"price_tol_pct": 1.0, "spread_mult": 0.5},
    "behavior": {
        "corr_threshold": 0.7,
        "dir_threshold": 0.75,
        "min_sig_moves": 10,
        "min_session_returns": 12,
    },
}


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def with_value(group: str, field: str, value: object) -> dict[str, dict[str, Any]]:
    data = {g: dict(v) for g, v in VALID.items()}
    data[group][field] = value
    return data


def test_valid_file_loads_into_groups(tmp_path: Path) -> None:
    assert load_thresholds(write(tmp_path, VALID)) == Thresholds.defaults()


def test_shipped_file_matches_defaults() -> None:
    assert load_thresholds(Path("config/thresholds.yaml")) == Thresholds.defaults()


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "absent.yaml"
    with pytest.raises(ConfigError, match=r"absent\.yaml"):
        load_thresholds(path)


def test_invalid_yaml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("candidates: [unclosed\n")
    with pytest.raises(ConfigError, match=r"broken\.yaml"):
        load_thresholds(path)


def test_non_mapping_document_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"thresholds\.yaml"):
        load_thresholds(write(tmp_path, ["a", "b"]))


def test_unknown_key_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"window\.colour"):
        load_thresholds(write(tmp_path, with_value("window", "colour", "blue")))


def test_unknown_group_fails(tmp_path: Path) -> None:
    data: dict[str, Any] = {**VALID, "extra": {}}
    with pytest.raises(ConfigError, match="extra"):
        load_thresholds(write(tmp_path, data))


def test_missing_field_fails(tmp_path: Path) -> None:
    data = {g: dict(v) for g, v in VALID.items()}
    del data["price"]["spread_mult"]
    with pytest.raises(ConfigError, match=r"price\.spread_mult"):
        load_thresholds(write(tmp_path, data))


@pytest.mark.parametrize(
    ("group", "field", "value"),
    [
        ("candidates", "name_ratio", 0),
        ("candidates", "name_ratio", 1.01),
        ("candidates", "max_name_candidates", 0),
        ("window", "sessions", 1),
        ("window", "embargo_minutes", -1),
        ("window", "min_bars", 1),
        ("window", "feed", "otc"),
        ("price", "price_tol_pct", 0),
        ("price", "spread_mult", -0.1),
        ("behavior", "corr_threshold", -1.01),
        ("behavior", "corr_threshold", 1.01),
        ("behavior", "dir_threshold", -0.01),
        ("behavior", "dir_threshold", 1.01),
        ("behavior", "min_sig_moves", 0),
        ("behavior", "min_session_returns", 0),
        ("window", "sessions", "twenty"),
    ],
)
def test_out_of_range_values_name_file_and_field(
    tmp_path: Path, group: str, field: str, value: object
) -> None:
    with pytest.raises(ConfigError, match=rf"thresholds\.yaml.*{group}\.{field}"):
        load_thresholds(write(tmp_path, with_value(group, field, value)))


def test_boundaries_are_accepted(tmp_path: Path) -> None:
    data = with_value("candidates", "name_ratio", 1)
    data["behavior"]["corr_threshold"] = -1
    data["behavior"]["dir_threshold"] = 0
    data["window"]["embargo_minutes"] = 0
    data["price"]["spread_mult"] = 0
    loaded = load_thresholds(write(tmp_path, data))
    assert loaded.candidates.name_ratio == 1
    assert loaded.behavior.corr_threshold == -1
