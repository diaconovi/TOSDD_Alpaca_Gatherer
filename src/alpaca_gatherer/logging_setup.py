"""Logging configuration: ``TIME_ZONE`` timestamps, ``run_id`` context and secret redaction.

>>> token = current_run_id.set("r1")
>>> current_run_id.get()
'r1'
>>> current_run_id.reset(token)
"""

import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = [
    "LOG_FORMAT",
    "RedactionFilter",
    "RunIdFilter",
    "ZonedFormatter",
    "configure_logging",
    "current_run_id",
    "mask",
    "register_secret",
    "reset_secrets",
]

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s run_id=%(run_id)s %(message)s"
MASK = "***"
_MIN_SECRET_LENGTH = 4

current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
"""Id of the run executing in the current task; ``None`` outside runs."""

_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Mask ``value`` in every log line from now on (values shorter than 4 chars are ignored)."""
    if len(value) >= _MIN_SECRET_LENGTH:
        _secrets.add(value)


def reset_secrets() -> None:
    """Forget every registered secret (used by tests)."""
    _secrets.clear()


def mask(text: str) -> str:
    """Replace every registered secret in ``text`` with ``***``.

    >>> register_secret("hunter22"); mask("pw=hunter22")
    'pw=***'
    >>> reset_secrets()
    """
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


class RunIdFilter(logging.Filter):
    """Adds ``run_id`` (``-`` outside runs) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = current_run_id.get() or "-"
        return True


class RedactionFilter(logging.Filter):
    """Masks registered secrets in the message, its arguments and any exception text."""

    _exc_formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        if _secrets:
            record.msg = mask(record.getMessage())
            record.args = None
            if record.exc_info and not record.exc_text:
                record.exc_text = self._exc_formatter.formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = mask(record.exc_text)
        return True


class ZonedFormatter(logging.Formatter):
    """Formats timestamps as ISO 8601 in a fixed IANA timezone and masks secrets once more."""

    def __init__(self, fmt: str = LOG_FORMAT, tz: str = "UTC") -> None:
        super().__init__(fmt)
        self._tz = ZoneInfo(tz)

    def formatTime(  # noqa: N802 - overrides logging.Formatter.formatTime
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        return datetime.fromtimestamp(record.created, self._tz).isoformat(timespec="milliseconds")

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "run_id"):
            record.run_id = current_run_id.get() or "-"
        return mask(super().format(record))


def configure_logging(level: str, tz: str) -> None:
    """Send every log record to stderr with ``run_id``, ``TIME_ZONE`` timestamps and redaction."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ZonedFormatter(LOG_FORMAT, tz))
    handler.addFilter(RunIdFilter())
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    for noisy in ("httpx", "httpcore", "pymongo", "apscheduler"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
