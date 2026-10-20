"""Retry policy shared by the gateways (research R14).

Exponential backoff with jitter, 5 attempts, on connection errors, HTTP 5xx and HTTP 429.
"""

import logging
from collections.abc import Callable

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

__all__ = ["ATTEMPTS", "DEFAULT_WAIT", "is_retryable_status", "retrying"]

log = logging.getLogger(__name__)

ATTEMPTS = 5
DEFAULT_WAIT: wait_base = wait_exponential_jitter(initial=1, max=30, jitter=1)


def is_retryable_status(status: int) -> bool:
    """True for HTTP 429 and 5xx.

    >>> is_retryable_status(429), is_retryable_status(503), is_retryable_status(404)
    (True, True, False)
    """
    return status == 429 or 500 <= status < 600


def retrying(
    retryable: Callable[[BaseException], bool],
    *,
    wait: wait_base = DEFAULT_WAIT,
    attempts: int = ATTEMPTS,
) -> AsyncRetrying:
    """An ``AsyncRetrying`` that retries ``retryable`` errors and re-raises the last one."""
    return AsyncRetrying(
        retry=retry_if_exception(retryable),
        stop=stop_after_attempt(attempts),
        wait=wait,
        reraise=True,
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
