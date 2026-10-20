"""Logging: timezone-aware timestamps, run_id injection and secret redaction (research R11)."""

import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from alpaca_gatherer.logging_setup import (
    RedactionFilter,
    RunIdFilter,
    ZonedFormatter,
    current_run_id,
    register_secret,
    reset_secrets,
)


@pytest.fixture(autouse=True)
def _clean_secrets() -> Iterator[None]:
    reset_secrets()
    yield
    reset_secrets()


def record(msg: str, *args: object) -> logging.LogRecord:
    rec = logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)
    rec.created = datetime(2026, 7, 1, 12, 0, tzinfo=UTC).timestamp()
    return rec


def render(rec: logging.LogRecord, tz: str = "UTC") -> str:
    formatter = ZonedFormatter("%(asctime)s run_id=%(run_id)s %(message)s", tz=tz)
    for f in (RunIdFilter(), RedactionFilter()):
        f.filter(rec)
    return formatter.format(rec)


def test_timestamp_rendered_in_configured_timezone() -> None:
    assert render(record("hi"), "America/Mexico_City").startswith("2026-07-01T06:00:00")
    assert render(record("hi"), "UTC").startswith("2026-07-01T12:00:00")


def test_run_id_placeholder_outside_runs() -> None:
    assert "run_id=- hi" in render(record("hi"))


def test_run_id_injected_from_context() -> None:
    token = current_run_id.set("run-42")
    try:
        assert "run_id=run-42 hi" in render(record("hi"))
    finally:
        current_run_id.reset(token)


def test_registered_secret_is_masked_in_message_and_args() -> None:
    register_secret("PKSECRETVALUE")
    out = render(record("key=%s and inline PKSECRETVALUE", "PKSECRETVALUE"))
    assert "PKSECRETVALUE" not in out
    assert "***" in out


def test_secret_in_exception_text_is_masked() -> None:
    register_secret("sup3rsecret")
    try:
        raise RuntimeError("failed with sup3rsecret")
    except RuntimeError:
        rec = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "boom", (), exc_info=sys.exc_info()
        )
    rec.created = 0
    assert "sup3rsecret" not in render(rec)


def test_short_values_are_not_registered() -> None:
    register_secret("")
    register_secret("ab")
    assert render(record("ab cd")).endswith("ab cd")
