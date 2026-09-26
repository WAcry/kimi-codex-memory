"""Small retry policy: external unavailability is not permanent source failure."""

from .errors import (
    BudgetError,
    BusyError,
    ConfigurationError,
    LeaseLostError,
    ModelError,
    ResyncRequired,
    TransportError,
)


def consumes_source_attempt(error: Exception) -> bool:
    if isinstance(
        error,
        (
            BudgetError,
            ConfigurationError,
            TransportError,
            BusyError,
            LeaseLostError,
            ResyncRequired,
            OSError,
        ),
    ):
        return False
    if isinstance(error, ModelError):
        if error.code in {
            "model_context_overflow",
            "model_request_too_large",
            "model_response_limit",
        }:
            return True
        if error.code in {
            "model_timeout",
            "model_connection",
            "model_overloaded",
            "model_abort",
            "model_process_exit",
            "model_requester_protocol",
            "model_rate_limit",
            "model_quota_exhausted",
        }:
            return False
        status = getattr(error, "status", None)
        if isinstance(status, int) and 400 <= status <= 599:
            return False
    return True
