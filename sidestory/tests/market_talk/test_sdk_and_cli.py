from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from supabase import ClientOptions, create_client

from sidestory.market_talk import __main__ as cli
from sidestory.market_talk.store import TalkStore
from sidestory.tests.market_talk.test_content_and_delivery import NOW, Store, sample


def test_real_sdk_rpc_schema_and_payload(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "SENDING", "token": "uuid"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    # postgrest 2.32 schema() creates a new HTTP client; intercept that transport too.
    monkeypatch.setattr("postgrest._sync.client.Client", lambda **kwargs: http)
    client = create_client(
        "https://example.supabase.co", "test-key", options=ClientOptions(httpx_client=http)
    )
    store = TalkStore(client)
    result = store.begin("page", "item", "talk", "본문", NOW.isoformat())
    assert result["status"] == "SENDING"
    request = requests[0]
    assert request.url.path == "/rest/v1/rpc/facebook_begin"
    assert request.headers["Content-Profile"] == "icg_side"
    assert json.loads(request.content)["p_page"] == "page"
    assert set(json.loads(request.content)) == {
        "p_page",
        "p_key",
        "p_track",
        "p_body_hash",
        "p_expires",
    }
    http.close()


def test_real_sdk_queue_filters_remain_read_only(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    # postgrest 2.32 schema() creates a new HTTP client; intercept that transport too.
    monkeypatch.setattr("postgrest._sync.client.Client", lambda **kwargs: http)
    store = TalkStore(
        create_client(
            "https://example.supabase.co", "test-key", options=ClientOptions(httpx_client=http)
        )
    )
    assert store.next_due("page", NOW) is None
    request = requests[0]
    assert request.method == "GET" and request.headers["Accept-Profile"] == "icg_side"
    assert request.url.params["page_id"] == "eq.page"
    assert request.url.params["status"] == "eq.APPROVED"
    assert request.url.params["expires_at"].startswith("gt.")
    http.close()


def test_cli_inspect_does_not_instantiate_publisher_or_llm(tmp_path, monkeypatch, capsys):
    draft = sample()
    path = tmp_path / "draft.json"
    path.write_text(draft.model_dump_json())
    store = Store(draft)
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("DRY_RUN", "false")  # inspect cannot be made live through the environment
    monkeypatch.setattr(cli, "connection", lambda: object())
    monkeypatch.setattr(cli, "TalkStore", lambda _: store)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setattr(cli, "current", lambda *a: ("b" * 64, "a" * 64))
    assert cli.main(["--input", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["allowed"] is False and store.writes == []


@pytest.mark.parametrize("name", ["DRY_RUN", "MARKET_TALK_LIVE", "FACEBOOK_CONTROL_ENABLED"])
def test_invalid_boolean_fails_closed(monkeypatch, name):
    monkeypatch.setenv(name, "treu")
    with pytest.raises(ValueError):
        cli.flag(name)


def test_no_approved_queue_is_normal_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setattr(cli, "connection", lambda: object())
    monkeypatch.setattr(
        cli,
        "TalkStore",
        lambda _: SimpleNamespace(
            next_due=lambda *a: None, require_hardening=lambda: None, record_outcome=lambda *a: None
        ),
    )
    output = tmp_path / "skip.json"
    assert cli.main(["--stage", "publish", "--live", "--output", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "SKIPPED_NO_APPROVED_CONTENT"
    assert json.loads(output.read_text()) == report


@pytest.mark.parametrize("note", ["", "short", "          "])
def test_missing_review_evidence_blocks_before_database(tmp_path, monkeypatch, capsys, note):
    def forbidden():
        pytest.fail("invalid human review must not reach the database")

    monkeypatch.setattr(cli, "connection", forbidden)
    output = tmp_path / "approval.json"
    assert (
        cli.main(
            [
                "--stage",
                "approve",
                "--revision",
                "a" * 64,
                "--confirm",
                "YES",
                "--actor",
                "reviewer",
                "--note",
                note,
                "--output",
                str(output),
            ]
        )
        == 1
    )
    report = json.loads(output.read_text())
    assert report == json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED" and report["blockers"] == ["REVIEW_NOTE_REQUIRED"]
    assert report["phase"] == "input" and report["run_id"]


def test_empty_inspect_reads_policy_without_write_or_provider(tmp_path, monkeypatch, capsys):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("postgrest._sync.client.Client", lambda **kwargs: http)
    client = create_client(
        "https://example.supabase.co", "test-key", options=ClientOptions(httpx_client=http)
    )
    monkeypatch.setattr(cli, "connection", lambda: client)
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("MARKET_TALK_CHARACTER_IDS", "")
    monkeypatch.setenv("MARKET_TALK_LIVE", "false")
    monkeypatch.setenv("FACEBOOK_CONTROL_ENABLED", "false")
    output = tmp_path / "report.json"
    assert cli.main(["--stage", "inspect", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report == json.loads(capsys.readouterr().out)
    assert report["status"] == "SETUP_REQUIRED" and report["allowed"] is False
    assert "PAGE_POLICY_REQUIRED" in report["blockers"]
    assert "CHARACTER_ALLOWLIST_REQUIRED" in report["blockers"]
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/rest/v1/facebook_page_policy"
    assert requests[0].url.params["page_id"] == "eq.123"
    assert requests[0].headers["Accept-Profile"] == "icg_side"
    http.close()


def test_inspect_configuration_never_claims_permission_or_publish_approval(monkeypatch):
    monkeypatch.setenv("MARKET_TALK_CHARACTER_IDS", "approved-id")
    monkeypatch.setenv("MARKET_TALK_LIVE", "true")
    monkeypatch.setenv("FACEBOOK_CONTROL_ENABLED", "true")
    store = SimpleNamespace(optional_policy=lambda _: {"enabled": True, "exclusive_managed": True})
    report = cli.readiness(store, "123")
    assert report["status"] == "INSPECTED" and report["blockers"] == []
    assert report["allowed"] is False and report["meta_permissions_verified"] is False
    assert report["needs_human_review"] is True


def test_cli_failure_artifact_does_not_leak_exception_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FACE_PAGE_ID", "123")

    def fail():
        raise ValueError("secret-token https://private.example/credentials")

    monkeypatch.setattr(cli, "connection", fail)
    output = tmp_path / "blocked.json"
    assert cli.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert json.loads(capsys.readouterr().out) == report
    assert report["status"] == "BLOCKED" and report["error_type"] == "ValueError"
    assert report["phase"] == "connection" and report["blockers"] == ["INVALID_INPUT_OR_STATE"]
    assert "secret-token" not in output.read_text() and "private.example" not in output.read_text()
