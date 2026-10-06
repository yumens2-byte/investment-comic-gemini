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


def test_no_approved_queue_is_normal_skip(monkeypatch, capsys):
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setattr(cli, "connection", lambda: object())
    monkeypatch.setattr(cli, "TalkStore", lambda _: SimpleNamespace(next_due=lambda *a: None))
    assert cli.main(["--stage", "publish", "--live"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED_NO_APPROVED_CONTENT"
