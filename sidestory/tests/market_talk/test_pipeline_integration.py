"""CLI -> real Supabase/Anthropic SDKs -> Graph adapter, isolated HTTP transports.

The HTTP fixture checks orchestration. SQL locking/permissions are tested separately
against PostgreSQL; no external credentials, provider charge or real publication.
"""

import json
from types import SimpleNamespace

import anthropic
import anthropic._base_client as anthropic_http
import httpx
import pytest
import requests
from supabase import ClientOptions, create_client

from sidestory.adapters.facebook.graph import FacebookPagePublisher
from sidestory.market_talk import __main__ as cli
from sidestory.tests.market_talk.test_automation import snapshot
from sidestory.tests.market_talk.test_content_and_delivery import NOW


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("success", "PUBLISHED"),
        ("missing_source", "BLOCKED"),
        ("review_reject", "SKIPPED_MODEL_REVIEW"),
        ("meta_timeout", "BLOCKED"),
        ("receipt_mismatch", "POSTED_UNVERIFIED"),
        ("finish_failure", "BLOCKED"),
        ("outcome_failure", "PUBLISHED_REPORT_PENDING"),
    ],
)
def test_automatic_pipeline_and_replay(monkeypatch, tmp_path, scenario, expected):
    state = dict(rows=[], costs=[], models=[], events=[], posts=[], delivery=None)
    db_requests, model_requests = [], []
    row = snapshot()
    if scenario == "missing_source":
        row["data_quality"]["source_status"] = {}

    def db_handler(request):
        db_requests.append(request)
        assert (
            request.headers.get("Content-Profile") or request.headers.get("Accept-Profile")
        ) == "icg_side"
        endpoint = request.url.path.rsplit("/", 1)[-1]
        data = json.loads(request.content) if request.content else {}
        if endpoint == "talk_contract_version":
            return httpx.Response(200, json=3)
        if endpoint == "market_talk_source_v1":
            return httpx.Response(200, json=[row])
        if endpoint == "facebook_page_policy":
            return httpx.Response(
                200,
                json=[
                    dict(
                        enabled=True,
                        exclusive_managed=True,
                        daily_budget_usd=1,
                        monthly_budget_usd=2,
                    )
                ],
            )
        if endpoint == "talk_items":
            if request.method == "POST":
                state["rows"].append(dict(data, status="DRAFT"))
            rows = state["rows"]
            if request.url.params.get("select") == "revision,semantic_key,body_hash,creative":
                rows = [dict(r) for r in rows]
            return httpx.Response(200, json=rows)
        if endpoint == "talk_cost_reserve":
            assert data["p_key"] not in state["costs"]
            state["costs"].append(data["p_key"])
        elif endpoint == "talk_model_state":
            state["models"].append(data)
        elif endpoint == "talk_approve":
            state["rows"][0]["status"] = "APPROVED"
            return httpx.Response(200, json=dict(status="APPROVED"))
        elif endpoint == "talk_hold":
            state["rows"][0]["status"] = "CONTENT_HOLD"
        elif endpoint == "facebook_observe":
            assert data["p_posts"] == []
        elif endpoint == "facebook_begin":
            if state["delivery"] is not None:
                return httpx.Response(200, json=dict(status="UNKNOWN"))
            state["delivery"] = dict(
                state="SENDING", body_hash=data["p_body_hash"], started_at=NOW.isoformat()
            )
            return httpx.Response(200, json=dict(status="SENDING", token="claim"))
        elif endpoint == "facebook_finish":
            if scenario == "finish_failure":
                return httpx.Response(
                    403, json=dict(code="42501", message="secret-token", details="", hint="")
                )
            state["delivery"].update(state=data["p_state"], post_id=data["p_post_id"])
            if data["p_state"] == "PUBLISHED":
                state["rows"][0]["status"] = "PUBLISHED"
        elif endpoint == "facebook_deliveries":
            return httpx.Response(200, json=[state["delivery"]])
        elif endpoint == "talk_record_outcome":
            if scenario == "outcome_failure":
                return httpx.Response(
                    403, json=dict(code="42501", message="secret-token", details="", hint="")
                )
            state["events"].append(data)
        else:
            pytest.fail("unexpected DB endpoint: " + endpoint)
        return httpx.Response(200, json=True)

    db_http = httpx.Client(transport=httpx.MockTransport(db_handler))
    monkeypatch.setattr("postgrest._sync.client.Client", lambda **kw: db_http)
    client = create_client(
        "https://example.supabase.co", "fixture", options=ClientOptions(httpx_client=db_http)
    )

    def model_handler(request):
        model_requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return model_http_module.Response(200, json=dict(input_tokens=100))
        body = json.loads(request.content)
        assert body["max_tokens"] in {300, 600}
        text = (
            dict(
                evidence_ids=["STORED_SNAPSHOT"],
                commentary="시장의 기록은 여러 신호를 함께 살피며 차분하게 읽어야 합니다.",
                dialogue="서두르지 말고 흐름을 하나씩 확인해 보자.",
            )
            if body["max_tokens"] == 600
            else dict(
                evidence_supported=True,
                canon_consistent=scenario != "review_reject",
                no_invented_events=True,
                no_trading_advice=True,
                readable_korean=True,
            )
        )
        return model_http_module.Response(
            200,
            json=dict(
                id="fixture",
                type="message",
                role="assistant",
                model="fixture",
                content=[dict(type="text", text=json.dumps(text, ensure_ascii=False))],
                stop_reason="end_turn",
                stop_sequence=None,
                usage=dict(input_tokens=100, output_tokens=100),
            ),
        )

    model_http_module = getattr(anthropic_http, "httpx2", httpx)
    model_http = model_http_module.Client(transport=model_http_module.MockTransport(model_handler))
    llm = anthropic.Anthropic(api_key="fixture", http_client=model_http, max_retries=0)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: llm)

    class GraphSession:
        def get(self, url, **kw):
            if url.endswith("/123/feed"):
                data = dict(data=[])
            elif url.endswith("/123"):
                data = dict(id="123")
            else:
                data = dict(
                    id="123_1",
                    message="wrong" if scenario == "receipt_mismatch" else state["posts"][0],
                    is_published=True,
                    created_time=NOW.isoformat(),
                )
            return SimpleNamespace(status_code=200, json=lambda: data)

        def post(self, url, **kw):
            assert url.endswith("/123/feed") and not kw.get("files")
            state["posts"].append(kw["data"]["message"])
            assert set(kw["data"]) == {"message", "access_token"}
            if scenario == "meta_timeout":
                raise requests.ReadTimeout("secret-token")
            return SimpleNamespace(status_code=200, json=lambda: dict(id="123_1"))

    monkeypatch.setattr(cli, "connection", lambda: client)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        cli,
        "live_publisher",
        lambda page: FacebookPagePublisher(page, "fixture", session=GraphSession()),
    )
    for key, value in dict(
        FACE_PAGE_ID="123",
        DRY_RUN="false",
        MARKET_TALK_LIVE="true",
        FACEBOOK_CONTROL_ENABLED="true",
        MARKET_TALK_AUTO_ENABLED="true",
        MARKET_TALK_CHARACTER_IDS="CHAR_HERO_001",
        GITHUB_SHA="a" * 40,
        MARKET_TALK_MODEL="fixture",
        MARKET_TALK_INPUT_USD_PER_MTOK="3",
        MARKET_TALK_OUTPUT_USD_PER_MTOK="15",
    ).items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "report.json"
    args = ["--stage", "automate", "--scheduled", "--live", "--output", str(output)]
    result = cli.main(args)
    report = json.loads(output.read_text())
    assert report["status"] == expected
    assert result == (
        1 if expected in {"BLOCKED", "POSTED_UNVERIFIED", "PUBLISHED_REPORT_PENDING"} else 0
    )
    assert "secret-token" not in output.read_text()
    if scenario == "missing_source":
        assert not model_requests and not state["posts"] and not state["costs"]
    else:
        assert len(state["costs"]) == 2 and len(state["models"]) == 4
        assert [m["p_state"] for m in state["models"]] == [
            "RESERVED",
            "COMPLETE",
            "RESERVED",
            "COMPLETE",
        ]
        assert len(state["posts"]) == (0 if scenario == "review_reject" else 1)
        previous = len(model_requests), len(state["posts"])
        cli.main(args)
        assert previous == (len(model_requests), len(state["posts"]))
    if scenario == "success":
        assert report["verified"] and state["events"][0]["p_code"] == "PUBLISHED_VERIFIED"
        assert "\n\nEDT : “" in state["posts"][0]
        assert "근거" not in state["posts"][0] and "STORED_SNAPSHOT" not in state["posts"][0]
    if scenario in {"meta_timeout", "finish_failure"}:
        assert state["delivery"]["state"] in {"UNKNOWN", "SENDING"}
    db_http.close()
    model_http.close()
