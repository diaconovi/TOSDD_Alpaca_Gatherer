"""Service settings (from ``.env``) and the threshold file loader.

Both fail fast with a ``ConfigError`` whose message names the variable, file or field at fault,
and never echoes a secret value.

>>> s = Settings.model_construct(collector_url="http://localhost:8001")
>>> s.collector_endpoint
('http', 'localhost', 8001)
"""

from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from cryptography.fernet import Fernet
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from alpaca_gatherer.domain.thresholds import (
    BehaviorThresholds,
    CandidateThresholds,
    PriceThresholds,
    Thresholds,
    WindowThresholds,
)

__all__ = ["ConfigError", "Settings", "load_settings", "load_thresholds"]

type Scheme = Literal["http", "https"]


class ConfigError(Exception):
    """A setting or the threshold file is missing or invalid; the service must not start."""


class Settings(BaseSettings):
    """Every environment setting of the service (data-model.md §6)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    collector_url: str
    mongo_url: str
    mongo_port: Annotated[int, Field(ge=1, le=65535)] = 27017
    mongo_mapping_db: Annotated[str, Field(min_length=1)]
    mongo_mapping_collection: str
    logging: Literal["INFO", "DEBUG", "WARNING"] = "INFO"
    time_zone: str = "UTC"
    field_encryption_key: SecretStr
    thresholds_file: Path = Path("config/thresholds.yaml")
    run_history_limit: int = 50
    alpaca_trading_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"

    @field_validator("collector_url")
    @classmethod
    def _collector_url(cls, value: str) -> str:
        parts = urlsplit(value)
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("must have a valid port") from exc
        if parts.scheme not in {"http", "https"} or not parts.hostname or port is None:
            raise ValueError(
                "must be an http(s) URL with host and port, e.g. http://localhost:8001"
            )
        return value

    @field_validator("mongo_url")
    @classmethod
    def _mongo_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "mongodb" or not parts.hostname:
            raise ValueError("must be a mongodb:// URL, e.g. mongodb://localhost")
        if parts.port is not None:
            raise ValueError("must not include a port; set MONGO_PORT instead")
        return value.rstrip("/")

    @field_validator("mongo_mapping_collection")
    @classmethod
    def _collection_name(cls, value: str) -> str:
        if not value or "$" in value or "." in value:
            raise ValueError("must be non-empty and contain neither '$' nor '.'")
        return value

    @field_validator("time_zone")
    @classmethod
    def _time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("must be a valid IANA timezone, e.g. America/Mexico_City") from exc
        return value

    @field_validator("field_encryption_key")
    @classmethod
    def _fernet_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "must be a Fernet key (generate one with Fernet.generate_key())"
            ) from exc
        return value

    @field_validator("run_history_limit")
    @classmethod
    def _history_limit(cls, value: int) -> int:
        if value < 50:
            raise ValueError("must be ≥ 50 (FR-012a minimum)")
        return value

    @field_validator("alpaca_trading_url", "alpaca_data_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("must be an http(s) URL")
        return value.rstrip("/")

    @property
    def collector_endpoint(self) -> tuple[Scheme, str, int]:
        """``COLLECTOR_URL`` split into ``(scheme, host, port)`` for the collector client."""
        parts = urlsplit(self.collector_url)
        scheme: Scheme = "https" if parts.scheme == "https" else "http"
        return scheme, parts.hostname or "", parts.port or (443 if scheme == "https" else 80)

    @property
    def mongo_uri(self) -> str:
        """Connection string built from ``MONGO_URL`` and ``MONGO_PORT``."""
        return f"{self.mongo_url}:{self.mongo_port}"


def _describe(exc: ValidationError, prefix: str = "") -> str:
    lines = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(part) for part in err["loc"])
        name = loc.upper() if not prefix else f"{prefix}{loc}"
        message = err["msg"].removeprefix("Value error, ")
        lines.append(f"{name}: {message}")
    return "; ".join(lines)


def load_settings(env_file: Path | str | None = ".env") -> Settings:
    """Read and validate the settings from the environment and ``env_file`` (if it exists)."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigError(f"Invalid settings: {_describe(exc)}") from None


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CandidatesModel(_Group):
    name_ratio: Annotated[float, Field(gt=0, le=1)]
    max_name_candidates: Annotated[int, Field(ge=1)]


class _WindowModel(_Group):
    sessions: Annotated[int, Field(ge=2)]
    embargo_minutes: Annotated[int, Field(ge=0)]
    min_bars: Annotated[int, Field(ge=2)]
    feed: Literal["sip", "iex"]


class _PriceModel(_Group):
    price_tol_pct: Annotated[float, Field(gt=0)]
    spread_mult: Annotated[float, Field(ge=0)]


class _BehaviorModel(_Group):
    corr_threshold: Annotated[float, Field(ge=-1, le=1)]
    dir_threshold: Annotated[float, Field(ge=0, le=1)]
    min_sig_moves: Annotated[int, Field(ge=1)]
    min_session_returns: Annotated[int, Field(ge=1)]


class _ThresholdsModel(_Group):
    candidates: _CandidatesModel
    window: _WindowModel
    price: _PriceModel
    behavior: _BehaviorModel

    def to_domain(self) -> Thresholds:
        return Thresholds(
            candidates=CandidateThresholds(**self.candidates.model_dump()),
            window=WindowThresholds(**self.window.model_dump()),
            price=PriceThresholds(**self.price.model_dump()),
            behavior=BehaviorThresholds(**self.behavior.model_dump()),
        )

    @classmethod
    def parse(cls, data: object) -> Self:
        return cls.model_validate(data)


def load_thresholds(path: Path) -> Thresholds:
    """Load and validate the threshold file (YAML, four groups, research R9)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"Thresholds file {path} (THRESHOLDS_FILE) does not exist") from None
    except OSError as exc:
        raise ConfigError(f"Thresholds file {path} cannot be read: {exc.strerror}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Thresholds file {path} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"Thresholds file {path} must contain a mapping of groups")
    try:
        return _ThresholdsModel.parse(data).to_domain()
    except ValidationError as exc:
        raise ConfigError(f"Thresholds file {path} is invalid: {_describe(exc, ' ')}") from None
