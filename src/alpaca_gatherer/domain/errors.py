"""Domain error hierarchy: one class per problem code.

Every error carries a stable ``code``, a short ``title`` and a ``detail`` that is safe to show to a
caller (it never contains credentials or exception text from a third party).

>>> err = RunInProgress("3f1c")
>>> err.code, err.active_run_id
('run_in_progress', '3f1c')
"""

from typing import ClassVar

__all__ = [
    "AlpacaAuthFailed",
    "AlpacaUnavailable",
    "CollectorIncompleteData",
    "CollectorUnavailable",
    "CredentialsExist",
    "CredentialsMissing",
    "CredentialsNotFound",
    "CredentialsUndecryptable",
    "DomainError",
    "InstrumentNotFound",
    "InvalidRequest",
    "MappingNotAvailable",
    "RunInProgress",
    "RunNotFound",
    "ScheduleValidationError",
]


class DomainError(Exception):
    """Base class of every error the service reports by code."""

    code: ClassVar[str] = "internal_error"
    title: ClassVar[str] = "Internal error"
    default_detail: ClassVar[str] = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class InvalidRequest(DomainError):
    """A request value failed a rule that the request schema alone cannot express."""

    code = "validation_error"
    title = "Validation error"
    default_detail = "The request is invalid."

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class ScheduleValidationError(InvalidRequest):
    """A schedule request is invalid; ``field`` names the offending field."""


class RunInProgress(DomainError):
    """A run is already executing."""

    code = "run_in_progress"
    title = "Run in progress"

    def __init__(self, active_run_id: str) -> None:
        self.active_run_id = active_run_id
        super().__init__(f"Run {active_run_id} is still running; wait for it to finish.")


class CredentialsMissing(DomainError):
    """A run was requested before Alpaca credentials were registered."""

    code = "credentials_missing"
    title = "Credentials missing"
    default_detail = "Register the Alpaca credentials (POST /api/v1/credentials) before running."


class CredentialsExist(DomainError):
    """Credentials are already registered."""

    code = "credentials_exist"
    title = "Credentials already registered"
    default_detail = "Alpaca credentials are already registered; use PATCH to replace them."


class CredentialsNotFound(DomainError):
    """An update was requested before credentials were registered."""

    code = "credentials_not_found"
    title = "Credentials not found"
    default_detail = "No Alpaca credentials are registered; use POST to register them first."


class RunNotFound(DomainError):
    """The run identifier is unknown or no longer retained."""

    code = "run_not_found"
    title = "Run not found"
    default_detail = "No retained run has this identifier."


class InstrumentNotFound(DomainError):
    """The identifier is not part of the stored mapping."""

    code = "instrument_not_found"
    title = "Instrument not found"
    default_detail = "The identifier is not in the stored mapping."


class MappingNotAvailable(DomainError):
    """No run has succeeded yet, so there is no mapping to look up."""

    code = "mapping_not_available"
    title = "Mapping not available"
    default_detail = "No matching run has succeeded yet; start one with POST /api/v1/runs."


class CredentialsUndecryptable(DomainError):
    """Stored credentials cannot be decrypted with the configured key."""

    code = "credentials_undecryptable"
    title = "Credentials cannot be decrypted"
    default_detail = (
        "The stored Alpaca credentials cannot be decrypted with the current encryption key; "
        "update them with PATCH /api/v1/credentials."
    )


class CollectorUnavailable(DomainError):
    """The collector could not be reached or kept failing after retries."""

    code = "collector_unavailable"
    title = "Collector unavailable"
    default_detail = "The collector service could not be reached."


class CollectorIncompleteData(DomainError):
    """The collector answered with data the run cannot use."""

    code = "collector_incomplete_data"
    title = "Collector returned incomplete data"
    default_detail = "The collector returned incomplete data."


class AlpacaUnavailable(DomainError):
    """Alpaca could not be reached, kept failing, or returned unusable data."""

    code = "alpaca_unavailable"
    title = "Alpaca unavailable"
    default_detail = "The Alpaca API could not be reached."


class AlpacaAuthFailed(DomainError):
    """Alpaca rejected the credentials (HTTP 401 or 403)."""

    code = "alpaca_auth_failed"
    title = "Alpaca rejected the credentials"
    default_detail = "Alpaca rejected the registered credentials; update them."
