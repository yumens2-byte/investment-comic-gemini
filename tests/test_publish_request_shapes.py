"""PR-02: every publication-path database write builds a valid PostgREST request."""
import ast
from pathlib import Path

import pytest

from tests.support.postgrest_capture import CapturingClient, assert_request_shape, body

ROW_VERSION = "2026-10-02T15:57:05.136865+00:00"


def _large_script():
    # Shape of ICG-2026-10-03-001 revision 2: reviewed image inputs make it ~68 KB.
    return {
        "panels": [{"idx": i, "action": "방패 " * 400} for i in range(1, 9)],
        "_reviewed_image_inputs": {"panels": [{"prompt_text": "x" * 8500}] * 6},
        "_state_candidate": {"version": "state-candidate-1", "base_arc": {"arc_day": 63}},
    }


@pytest.fixture
def client(monkeypatch):
    def responder(request):
        if request.url.path.endswith("/rpc/publication_state_preflight"):
            return {"ready": True}
        if request.url.path.endswith("/rpc/record_episode_delivery"):
            return {"recorded": True}
        if request.url.path.endswith("/rpc/finalize_episode_publication"):
            return {"committed": True}
        if request.method == "PATCH":
            return [body(request)]
        return []

    fake = CapturingClient(responder)
    from engine.common import supabase_client

    monkeypatch.setattr(supabase_client, "get_client", lambda: fake)
    monkeypatch.setattr(supabase_client, "icg_table", lambda name: fake.table(name))
    return fake


def test_claim_and_release_requests_are_bounded_and_json(client):
    from engine.publish.claim_guard import claim_publication, finish_publication

    row = {"status": "assembled", "error_message": None, "script_json": _large_script(),
           "updated_at": ROW_VERSION}
    token = claim_publication(row, "2026-10-03", 1)
    finish_publication("2026-10-03", 1, token)
    assert len(client.requests) == 2
    for request in client.requests:
        assert_request_shape(request)
        assert "script_json" not in str(request.url)
    assert "updated_at=eq." in str(client.requests[0].url)


def test_state_and_delivery_rpcs_send_json_bodies(client):
    from engine.publish.state_commit import record_delivery, require_state_ready

    candidate = _large_script()["_state_candidate"]
    require_state_ready("2026-10-03", 1, candidate)
    record_delivery("2026-10-03", 1, "PUBLISH_HOLD:x", "x", ["2105757754312851782"])
    record_delivery("2026-10-03", 1, "PUBLISH_HOLD:x", "telegram:@chan", [123])
    for request in client.requests:
        assert_request_shape(request)
        assert request.method == "POST"
    assert body(client.requests[0])["p_candidate"] == candidate
    assert body(client.requests[2])["p_ids"] == [123]


def test_finalize_rpc_sends_json_body(client, monkeypatch):
    from engine.publish.history_writer import record_publish

    monkeypatch.delenv("GITHUB_SHA", raising=False)

    record_publish(
        episode_date="2026-10-03", episode_id="ICG-2026-10-03-001", event_type="BATTLE",
        tweet_ids=["1"], telegram_sent=True, slide_count=8, gemini_cost_usd=0.2375,
        claude_cost_usd=0.0, runtime_sec=12.3,
        state_candidate=_large_script()["_state_candidate"],
        telegram_receipts={"@chan": [123]},
    )
    (request,) = client.requests
    assert_request_shape(request)
    assert request.url.path.endswith("/rpc/finalize_episode_publication")
    assert body(request)["p_telegram"] == {"@chan": [123]}


FILTER_METHODS = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is_", "in_",
                  "contains", "contained_by"}


def _json_filter_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in FILTER_METHODS and len(node.args) >= 2):
            continue
        column, value = node.args[0], node.args[1]
        json_column = (isinstance(column, ast.Constant) and isinstance(column.value, str)
                       and column.value.endswith("_json"))
        literal = isinstance(value, (ast.Dict, ast.DictComp))
        if json_column or literal:
            yield f"{path}:{node.lineno}"


def test_no_jsonb_or_dict_url_filters_in_production_code():
    roots = [Path("engine"), Path("scripts")]
    offenders = [hit for root in roots for path in root.rglob("*.py")
                 if "__pycache__" not in path.parts for hit in _json_filter_calls(path)]
    assert offenders == []


def test_rehearsal_builds_without_sending(client):
    from engine.publish.claim_guard import rehearse_publication_requests

    row = {"status": "assembled", "error_message": None, "script_json": _large_script(),
           "updated_at": ROW_VERSION}
    assert rehearse_publication_requests(row, "2026-10-03", 1) == []
    assert client.requests == []  # built only, never sent


def test_rehearsal_reports_missing_row_version(client):
    from engine.publish.claim_guard import rehearse_publication_requests

    row = {"status": "assembled", "error_message": None, "script_json": _large_script()}
    issues = rehearse_publication_requests(row, "2026-10-03", 1)
    assert issues and issues[0].startswith("claim_request_invalid:")
    assert client.requests == []


def test_preflight_surfaces_rehearsal_issue(monkeypatch, client):
    from engine.publish import claim_guard
    from scripts import publish_preflight

    monkeypatch.setattr(claim_guard, "rehearse_publication_requests",
                        lambda *a: ["claim_request_url_too_long:90000"])
    calls = []

    class Rows:
        def __init__(self, name):
            self.name = name

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def limit(self, *_):
            return self

        def execute(self):
            calls.append(self.name)
            from types import SimpleNamespace
            if self.name == "episode_assets":
                return SimpleNamespace(data=[{"status": "assembled", "event_type": "BATTLE",
                                              "error_message": None, "script_json": {},
                                              "slides_json": []}])
            return SimpleNamespace(data=[])

    from engine.common import supabase_client
    monkeypatch.setattr(supabase_client, "icg_table", Rows)
    report = publish_preflight.inspect_publish("ICG-2026-10-03-001", None, "telegram",
                                               dry_run=True)
    assert "publish_request_invalid:claim_request_url_too_long:90000" in report["readiness_issues"]
    assert report["live_publish_ready"] is False


def test_finalize_records_code_sha_with_bounded_request(client, monkeypatch):
    from engine.publish.history_writer import record_publish

    sha = "a" * 40
    monkeypatch.setenv("GITHUB_SHA", sha)
    record_publish(
        episode_date="2026-10-03", episode_id="ICG-2026-10-03-001", event_type="BATTLE",
        tweet_ids=["1"], telegram_sent=False, slide_count=8, gemini_cost_usd=0.1,
        claude_cost_usd=0.0, runtime_sec=1.0,
        state_candidate={"version": "state-candidate-1"}, telegram_receipts={},
    )
    finalize, code_sha = client.requests
    for request in client.requests:
        assert_request_shape(request)
    assert code_sha.method == "PATCH" and code_sha.url.path.endswith("/published_comics")
    assert body(code_sha) == {"code_sha": sha}
