"""Safe operational errors: no exception messages, request URLs or source text."""

from sidestory.market_talk.policy import PolicyError
from sidestory.ports.publisher import PublishError


class PhaseFailure(RuntimeError):
    def __init__(self, phase, original):
        self.phase, self.original = phase, original
        super().__init__(phase)


class DeliveryError(PublishError):
    def __init__(self, code, *, ambiguous=False, phase="delivery"):
        self.code, self.phase = code, phase
        super().__init__(code, ambiguous=ambiguous)


def phase_call(phase, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (PolicyError, DeliveryError, PhaseFailure):
        raise
    except Exception as exc:
        # Keep the established typed model parse exception unchanged.
        from sidestory.market_talk.generation import ModelResponseError

        if isinstance(exc, ModelResponseError):
            raise
        raise PhaseFailure(phase, exc) from None


# Graph error codes: developers.facebook.com/docs/graph-api/guides/error-handling
FACEBOOK_TOKEN_CODES = {102, 190}
FACEBOOK_RATE_CODES = {4, 17, 32, 341, 613}
FACEBOOK_TRANSIENT_CODES = {1, 2}


def facebook_code(exc):
    """Map an adapter PublishError to a safe enum; never reads the message text."""
    kind, status, code = (getattr(exc, name, None) for name in ("kind", "http_status", "provider_code"))
    if kind == "connect_timeout" or kind == "timeout":
        return "PROVIDER_TIMEOUT"
    if kind == "transport":
        return "PROVIDER_CONNECTION_FAILURE"
    if kind == "credentials":
        return "FACEBOOK_CREDENTIALS_MISSING"
    if kind == "page_mismatch":
        return "FACEBOOK_PAGE_MISMATCH"
    if kind != "http":
        return "FACEBOOK_API_FAILURE"
    if code in FACEBOOK_TOKEN_CODES or status == 401:
        return "FACEBOOK_TOKEN_INVALID"
    if code in FACEBOOK_RATE_CODES or status == 429:
        return "FACEBOOK_RATE_LIMITED"
    if code in FACEBOOK_TRANSIENT_CODES or (status or 0) >= 500:
        return "FACEBOOK_UNAVAILABLE"
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299) or status == 403:
        return "FACEBOOK_PERMISSION_DENIED"
    return "FACEBOOK_API_FAILURE"


def failure_report(exc, phase):
    from sidestory.market_talk.generation import ModelResponseError

    if isinstance(exc, PhaseFailure):
        phase, exc = exc.phase, exc.original
    phase = getattr(exc, "phase", phase)
    code = "UNEXPECTED_FAILURE"
    if isinstance(exc, (PolicyError, DeliveryError, ModelResponseError)):
        code = exc.code
    elif type(exc).__name__ == "APIError":
        code = {
            "42501": "DB_PERMISSION_DENIED",
            "23505": "DB_DUPLICATE_RESERVATION_OR_KEY",
            "PGRST106": "DB_SCHEMA_NOT_EXPOSED",
            "PGRST202": "DB_MIGRATION_REQUIRED",
            "42P01": "DB_MIGRATION_REQUIRED",
            "PGRST205": "DB_MIGRATION_REQUIRED",
            "P0001": "DB_POLICY_REJECTED",
        }.get(getattr(exc, "code", None), "DB_API_FAILURE")
    elif isinstance(exc, PublishError):
        code = facebook_code(exc)
    elif isinstance(exc, ValueError):
        code = "INVALID_INPUT_OR_STATE"
    elif "Timeout" in type(exc).__name__:
        code = "PROVIDER_TIMEOUT"
    elif "Connection" in type(exc).__name__:
        code = "PROVIDER_CONNECTION_FAILURE"
    report = {
        "status": "BLOCKED",
        "error_type": type(exc).__name__,
        "phase": phase,
        "blockers": [code],
        "automatic_retry": False,
        "reservation_retained": phase
        in {"generation", "review", "generation_reservation", "review_reservation"},
        "outcome_unknown": getattr(exc, "ambiguous", False) or phase in {"generation", "review"},
    }
    if isinstance(exc, PublishError):
        # Integers only: status and Graph error code are safe for operator reports.
        for key, name in (("provider_status", "http_status"), ("provider_code", "provider_code")):
            value = getattr(exc, name, None)
            if isinstance(value, int) and not isinstance(value, bool):
                report[key] = value
    return report
