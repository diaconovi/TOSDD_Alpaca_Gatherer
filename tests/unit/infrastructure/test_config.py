"""Settings validation (data-model.md §6)."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from alpaca_gatherer.config import ConfigError, Settings, load_settings

SETTING_NAMES = (
    "COLLECTOR_URL",
    "MONGO_URL",
    "MONGO_PORT",
    "MONGO_MAPPING_DB",
    "MONGO_MAPPING_COLLECTION",
    "LOGGING",
    "TIME_ZONE",
    "FIELD_ENCRYPTION_KEY",
    "THRESHOLDS_FILE",
    "RUN_HISTORY_LIMIT",
    "ALPACA_TRADING_URL",
    "ALPACA_DATA_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)


def required(**overrides: str) -> dict[str, str]:
    values = {
        "COLLECTOR_URL": "http://localhost:8001",
        "MONGO_URL": "mongodb://localhost",
        "MONGO_MAPPING_DB": "gatherer",
        "MONGO_MAPPING_COLLECTION": "mapping",
        "FIELD_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    values.update(overrides)
    return values


def load(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> Settings:
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return load_settings(env_file=None)


def test_defaults_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(monkeypatch, required())
    assert settings.mongo_port == 27017
    assert settings.logging == "INFO"
    assert settings.time_zone == "UTC"
    assert settings.thresholds_file == Path("config/thresholds.yaml")
    assert settings.run_history_limit == 50
    assert settings.alpaca_trading_url == "https://paper-api.alpaca.markets"
    assert settings.alpaca_data_url == "https://data.alpaca.markets"


def test_collector_endpoint_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(monkeypatch, required(COLLECTOR_URL="https://collector.internal:8443"))
    assert settings.collector_endpoint == ("https", "collector.internal", 8443)


def test_mongo_uri_joins_url_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(monkeypatch, required(MONGO_PORT="27018"))
    assert settings.mongo_uri == "mongodb://localhost:27018"


def test_missing_encryption_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    values = required()
    del values["FIELD_ENCRYPTION_KEY"]
    with pytest.raises(ConfigError, match="FIELD_ENCRYPTION_KEY"):
        load(monkeypatch, values)


def test_non_fernet_key_fails_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="FIELD_ENCRYPTION_KEY") as info:
        load(monkeypatch, required(FIELD_ENCRYPTION_KEY="not-a-key"))
    assert "not-a-key" not in str(info.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TIME_ZONE", "Mars/Base"),
        ("LOGGING", "ERROR"),
        ("RUN_HISTORY_LIMIT", "49"),
        ("MONGO_MAPPING_COLLECTION", "map$ping"),
        ("MONGO_MAPPING_COLLECTION", "map.ping"),
        ("MONGO_MAPPING_DB", ""),
        ("COLLECTOR_URL", "http://:8001"),
        ("COLLECTOR_URL", "localhost:8001"),
        ("COLLECTOR_URL", "http://localhost"),
        ("MONGO_URL", "mongodb://localhost:27017"),
        ("MONGO_URL", "http://localhost"),
        ("MONGO_PORT", "0"),
        ("ALPACA_DATA_URL", "data.alpaca.markets"),
    ],
)
def test_invalid_values_fail_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    with pytest.raises(ConfigError, match=name):
        load(monkeypatch, required(**{name: value}))


def test_run_history_minimum_message(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match=r"≥ 50 \(FR-012a minimum\)"):
        load(monkeypatch, required(RUN_HISTORY_LIMIT="49"))


@pytest.mark.parametrize("name", ["COLLECTOR_URL", "MONGO_URL", "MONGO_MAPPING_COLLECTION"])
def test_missing_required_variable_fails(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    values = required()
    del values[name]
    with pytest.raises(ConfigError, match=name):
        load(monkeypatch, values)


def test_reads_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in required(TIME_ZONE="Europe/Madrid").items()))
    assert load_settings(env_file=env).time_zone == "Europe/Madrid"
