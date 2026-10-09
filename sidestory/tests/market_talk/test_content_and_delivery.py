from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sidestory.market_talk.content import Context, Copy, Draft, digest, validate
from sidestory.market_talk.diagnostics import PhaseFailure
from sidestory.market_talk.generation import generate
from sidestory.market_talk.publishing import ControlledPublisher
from sidestory.market_talk.service import inspect, publish
from sidestory.ports.publisher import PublishError

NOW = datetime(2026, 10, 6, 9, 30, tzinfo=timezone.utc)


def sample():
    return Draft(
        context=Context(
            topic="금리",
            claim_key="close-20261005-us10y",
            kind="market_close",
            snapshot_date="2026-10-06",
            snapshot_hash="a" * 64,
            canon_version="b" * 64,
            character_id="CHAR_HERO_001",
            character_name="EDT",
            character_voice={"truth": "회복력"},
            evidence=[
                dict(
                    id="us10y:20261005",
                    statement="테스트 금리 4.0%.",
                    source_url="https://example.org/fixture",
                    observed_at=NOW - timedelta(hours=12),
                    market_session="test-close",
                )
            ],
            expires_at=NOW + timedelta(hours=5),
            provenance_reviewer="reviewer",
            provenance_note="fixture only",
        ),
        text=Copy(
            evidence_ids=["us10y:20261005"],
            commentary="시장의 기록을 읽을 때는 기준 시점을 함께 확인합니다.",
            dialogue="한 번의 신호만으로 결론을 내리지는 말자.",
        ),
        due_at=NOW,
    )


class Store:
    def __init__(self, draft=None):
        self.draft = draft or sample()
        self.state = None
        self.token = "claim"
        self.sent = 0
        self.writes = []
        self.fail_finish = False
        self.cost = set()
        self.model_events = []
        self.outcomes = []

    def require_hardening(self):
        return None

    def record_outcome(self, *args):
        self.outcomes.append(args)

    def model_state(self, *args):
        self.model_events.append(args)

    def delivery(self, page, revision):
        return dict(
            state=self.state,
            post_id="123_1",
            body_hash=digest(self.draft.body),
            started_at=NOW.isoformat(),
        )

    def recent(self, page):
        return []

    def policy(self, page):
        return {"enabled": True}

    def item(self, revision):
        return {
            "revision": revision,
            "payload": self.draft.model_dump(mode="json"),
            "body": self.draft.body,
            "page_id": "123",
            "status": "PUBLISHED" if self.state == "PUBLISHED" else "APPROVED",
        }

    def observe(self, page, posts):
        self.writes.append("observe")

    def begin(self, *args):
        self.writes.append("begin")
        if self.state == "PUBLISHED":
            return {"status": "PUBLISHED", "post_id": "123_1"}
        if self.state in {"SENDING", "UNKNOWN"}:
            return {"status": "UNKNOWN"}
        self.state = "SENDING"
        return {"status": "SENDING", "token": self.token}

    def finish(self, page, key, token, state, **kwargs):
        assert token == self.token
        if self.fail_finish:
            raise RuntimeError("db unavailable")
        self.state = state
        if hasattr(self, "row") and self.row and state == "PUBLISHED":
            self.row["status"] = state
        self.writes.append(state)

    def cost_reserve(self, page, key, amount):
        if key in self.cost:
            raise ValueError("duplicate request")
        self.cost.add(key)
        self.writes.append(("cost", amount))


class Provider:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def check(self):
        return {"id": "123"}

    def recent_receipts(self, since):
        return []

    def create_post(self, message, photos):
        self.calls += 1
        self.message = message
        if self.error:
            raise self.error
        return "123_1"

    def get_post(self, post_id):
        return dict(
            id=post_id, message=self.message, is_published=True, created_time=NOW.isoformat()
        )


def check(d, **kwargs):
    return validate(
        d,
        now=NOW,
        current_canon="b" * 64,
        current_snapshot="a" * 64,
        recent=kwargs.get("recent", []),
    )


def test_grounded_render_is_separate_from_fiction():
    d = sample()
    assert check(d) == []
    assert "4.0%" in d.body and "창작 대사" in d.body and "test-close" in d.body
    assert d.revision == digest(d.model_dump(mode="json"))


@pytest.mark.parametrize(
    "text",
    ["지금 급등하고 있으니", "금리는 5%입니다", "수익 보장 가능한 시장", "좋아요 눌러 주세요"],
)
def test_unsupported_creative_claims(text):
    d = sample().model_copy(update={"text": sample().text.model_copy(update={"commentary": text})})
    assert check(d)


def test_stale_or_changed_evidence():
    d = sample()
    assert validate(
        d, now=d.context.expires_at, current_canon="b" * 64, current_snapshot="a" * 64, recent=[]
    ) == ["expired"]
    assert "snapshot_changed" in validate(
        d, now=NOW, current_canon="b" * 64, current_snapshot="c" * 64, recent=[]
    )
    assert "canon_changed" in validate(
        d, now=NOW, current_canon="c" * 64, current_snapshot="a" * 64, recent=[]
    )


def test_future_evidence_and_unknown_fact():
    d = sample()
    e = d.context.evidence[0].model_copy(update={"observed_at": NOW + timedelta(hours=1)})
    d = d.model_copy(update={"context": d.context.model_copy(update={"evidence": [e]})})
    assert "future_evidence" in check(d)
    d = sample().model_copy(
        update={"text": sample().text.model_copy(update={"evidence_ids": ["missing"]})}
    )
    assert "unknown_or_duplicate_evidence" in check(d)


def test_same_claim_different_character_is_duplicate():
    d = sample()
    second = d.model_copy(
        update={"context": d.context.model_copy(update={"character_id": "other"})}
    )
    assert d.semantic_key == second.semantic_key
    assert "duplicate_content" in check(second, recent=[{"semantic_key": d.semantic_key}])


def test_rewording_changes_approval_revision():
    d = sample()
    second = d.model_copy(
        update={"text": d.text.model_copy(update={"dialogue": "다른 이야기를 해 보자."})}
    )
    assert d.revision != second.revision


def test_dry_run_has_no_writes():
    store = Store()
    report = inspect(sample(), store, "123", now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64)
    assert report["allowed"] is False and report["needs_human_review"]
    assert store.writes == []


def test_approved_pipeline_publishes_once_without_images():
    d, store, provider = sample(), Store(), Provider()
    publisher = ControlledPublisher(provider, store, "123", d.revision, "talk")
    for _ in range(2):
        assert (
            publish(
                d.revision, store, publisher, now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64
            )["status"]
            == "PUBLISHED"
        )
    assert provider.calls == 1


@pytest.mark.parametrize(
    "error", [PublishError("timeout", ambiguous=True), RuntimeError("unexpected")]
)
def test_unknown_never_reposts(error):
    s, p = Store(), Provider(error)
    pub = ControlledPublisher(p, s, "123", "key", "talk")
    for _ in range(2):
        with pytest.raises(PublishError):
            pub.create_post("body", [])
    assert s.state == "UNKNOWN" and p.calls == 1


def test_lost_receipt_blocks_another_worker():
    s, p = Store(), Provider()
    s.fail_finish = True
    pub = ControlledPublisher(p, s, "123", "key", "talk")
    with pytest.raises(PublishError):
        pub.create_post("body", [])
    s.fail_finish = False
    with pytest.raises(PublishError):
        ControlledPublisher(p, s, "123", "key", "talk").create_post("body", [])
    assert p.calls == 1 and s.state == "SENDING"


def test_no_publish_before_due_or_without_approval():
    d = sample().model_copy(update={"due_at": NOW + timedelta(hours=1)})
    s, p = Store(d), Provider()
    assert (
        publish(d.revision, s, p, now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64)["status"]
        == "NOT_DUE"
    )
    assert p.calls == 0


def test_missing_page_history_blocks_without_send():
    p, s = Provider(), Store()
    p.recent_receipts = lambda _: (_ for _ in ()).throw(PublishError("history incomplete"))
    with pytest.raises(PublishError):
        ControlledPublisher(p, s, "123", "key", "talk").create_post("body", [])
    assert p.calls == 0 and s.writes == []


def test_paid_preview_reserved_once_and_token_bounded():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=sample().text.model_dump_json())],
        )

    client = SimpleNamespace(
        messages=SimpleNamespace(
            count_tokens=lambda **kw: SimpleNamespace(input_tokens=100), create=create
        )
    )
    s = Store()
    result = generate(
        sample().context, s, "123", model="test-model", input_rate=1, output_rate=2, client=client
    )
    assert result == sample().text and calls[0]["max_tokens"] == 600
    with pytest.raises(PhaseFailure, match="reservation"):
        generate(
            sample().context,
            s,
            "123",
            model="test-model",
            input_rate=1,
            output_rate=2,
            client=client,
        )
    assert len(calls) == 1
    with pytest.raises(ValueError):
        generate(
            sample().context,
            s,
            "123",
            model="test-model",
            input_rate=1,
            output_rate=2,
            attempt=3,
            client=client,
        )


def test_tampered_stored_body_refused():
    s = Store()
    orig = s.item
    s.item = lambda revision: {**orig(revision), "body": "tampered"}
    with pytest.raises(ValueError, match="hash mismatch"):
        publish(
            sample().revision, s, Provider(), now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64
        )


def test_missed_day_is_not_caught_up():
    d = sample().model_copy(update={"due_at": NOW - timedelta(days=1)})
    assert "missed_slot" in check(d)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "456_1"},
        {"message": "unrelated"},
        {"is_published": False},
        {"created_time": "2025-01-01T00:00:00Z"},
    ],
)
def test_reconcile_requires_exact_content_page_and_time(change):
    from sidestory.market_talk.service import verified_receipt

    receipt = {
        "id": "123_1",
        "message": "reviewed",
        "is_published": True,
        "created_time": NOW.isoformat(),
    }
    delivery = {"body_hash": digest("reviewed"), "started_at": NOW.isoformat()}
    with pytest.raises(ValueError):
        verified_receipt("123", "123_1", {**receipt, **change}, delivery, NOW)
    assert verified_receipt("123", "123_1", receipt, delivery, NOW) == NOW.isoformat()
