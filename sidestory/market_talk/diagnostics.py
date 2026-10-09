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
    return report
