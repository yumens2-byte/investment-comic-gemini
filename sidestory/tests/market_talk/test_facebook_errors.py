"""Facebook Graph failures must surface as safe, specific codes (2026-10-27 incident)."""

from types import SimpleNamespace

import pytest
import requests

from sidestory.adapters.facebook.graph import FacebookPagePublisher
from sidestory.market_talk.diagnostics import DeliveryError, PhaseFailure, failure_report
from sidestory.market_talk.recovery import retryable
from sidestory.ports.publisher import PublishError

TOKEN = "secret-token-value"


class Session:
    def __init__(self, outcome):
        self.outcome = outcome

    def get(self, *args, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        status, body = self.outcome
        return SimpleNamespace(status_code=status, json=lambda: body)


def page_check_failure(outcome):
    publisher = FacebookPagePublisher("123", TOKEN, session=Session(outcome))
    with pytest.raises(PublishError) as exc:
        publisher.check()
    return failure_report(PhaseFailure("page_identity", exc.value), "execution")


def graph_error(status, code):
    return status, {"error": {"code": code, "type": "OAuthException", "message": TOKEN}}


@pytest.mark.parametrize(
    "outcome,expected,retry",
    [
        (graph_error(400, 190), "FACEBOOK_TOKEN_INVALID", False),
        (graph_error(403, 200), "FACEBOOK_PERMISSION_DENIED", False),
        (graph_error(400, 10), "FACEBOOK_PERMISSION_DENIED", False),
        (graph_error(400, 4), "FACEBOOK_RATE_LIMITED", True),
        (graph_error(500, 2), "FACEBOOK_UNAVAILABLE", True),
        (graph_error(503, None), "FACEBOOK_UNAVAILABLE", True),
        (graph_error(400, 100), "FACEBOOK_API_FAILURE", False),
        ((200, {"id": "999"}), "FACEBOOK_PAGE_MISMATCH", False),
        (requests.ConnectTimeout("slow"), "PROVIDER_TIMEOUT", True),
        (requests.ReadTimeout("slow"), "PROVIDER_TIMEOUT", True),
        (requests.ConnectionError("reset"), "PROVIDER_CONNECTION_FAILURE", True),
    ],
)
def test_page_identity_failures_are_classified(outcome, expected, retry):
    report = page_check_failure(outcome)
    assert report["blockers"] == [expected]
    assert report["phase"] == "page_identity" and report["error_type"] == "PublishError"
    assert report["outcome_unknown"] is False
    assert retryable(report) is retry
    assert TOKEN not in str(report)


def test_graph_status_and_code_are_reported_as_integers_only():
    report = page_check_failure(graph_error(400, 190))
    assert report["provider_status"] == 400 and report["provider_code"] == 190


def test_unclassified_publish_error_is_no_longer_unexpected():
    report = failure_report(PhaseFailure("page_identity", PublishError("boom")), "execution")
    assert report["blockers"] == ["FACEBOOK_API_FAILURE"] and not retryable(report)


def test_delivery_errors_keep_their_own_codes_and_never_retry():
    report = failure_report(DeliveryError("FACEBOOK_UNAVAILABLE", ambiguous=True), "delivery")
    assert report["blockers"] == ["FACEBOOK_UNAVAILABLE"] and not retryable(report)
