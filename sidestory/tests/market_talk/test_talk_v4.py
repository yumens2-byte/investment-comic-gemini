"""Regression coverage for talk-only gates and pre-cost readiness."""

import pytest

from sidestory.market_talk import automation as auto
from sidestory.market_talk.publishing import TalkPublisher
from sidestory.market_talk.service import publish
from sidestory.tests.market_talk.test_automation import AutoStore, execute
from sidestory.tests.market_talk.test_content_and_delivery import NOW, Provider, Store


def test_talk_publishes_and_verifies_with_broken_feed():
    store, provider = Store(), Provider()
    provider.recent_receipts = lambda *a: pytest.fail("feed must never be read")
    store.observe = lambda *a: pytest.fail("page observation forbidden")
    pub = TalkPublisher(provider, store, "123", store.draft.revision, "talk")
    result = publish(
        store.draft.revision, store, pub, now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64
    )
    assert result["verified"] is True
    assert provider.calls == 1
    # Repeated delivery uses the persisted receipt, no second POST.
    assert pub.create_post(store.draft.body, []) == "123_1"
    assert provider.calls == 1


@pytest.mark.parametrize(
    "state", ["WAITING_SLOT", "MISSED_WINDOW", "UNKNOWN", "TALK_LIMIT", "CHANNEL_HOLD"]
)
def test_readiness_blocks_before_any_source_or_model(monkeypatch, state):
    store = AutoStore()
    store.preflight = lambda *a: {"status": state}
    result = execute(store, monkeypatch)
    assert result["status"] == state
    assert store.writes == []
    assert result["paid_call_count"] == 0


def test_identity_failure_prevents_paid_generation(monkeypatch):
    store = AutoStore()
    from sidestory.tests.market_talk.test_content_and_delivery import sample

    monkeypatch.setattr(auto, "prepare_context", lambda *a: (sample().context, NOW))
    monkeypatch.setattr(auto, "generate", lambda *a, **kw: pytest.fail("paid call"))

    def fail():
        raise ValueError("identity unavailable")

    with pytest.raises(Exception):
        auto.automatic_draft(
            None,
            store,
            "123",
            canon_path=None,
            allowed={"EDT"},
            now=NOW,
            source_commit="a" * 40,
            model="fixture",
            input_rate=1,
            output_rate=2,
            current=None,
            page_check=fail,
        )
    assert store.writes == []


@pytest.mark.parametrize(
    "status",
    [
        "WAITING_SLOT",
        "MISSED_WINDOW",
        "ALREADY_PUBLISHED",
        "POLICY_NOT_EFFECTIVE",
        "SLOT_REQUIRED",
        "LEGACY_SLOT",
    ],
)
def test_send_gate_preserves_v4_safe_reason(status):
    from sidestory.market_talk.diagnostics import DeliveryError

    store, provider = Store(), Provider()
    store.begin = lambda *args: {"status": status}
    with pytest.raises(DeliveryError) as error:
        TalkPublisher(provider, store, "123", "revision", "talk").create_post("body", [])
    assert str(error.value) == status
    assert provider.calls == 0


@pytest.mark.parametrize(
    "status,exit_code",
    [
        ("UNKNOWN", 1),
        ("CHANNEL_HOLD", 1),
        ("POLICY_NOT_EFFECTIVE", 1),
        ("LEGACY_SLOT", 1),
        ("WAITING_SLOT", 0),
        ("MISSED_WINDOW", 0),
        ("ALREADY_PUBLISHED", 0),
    ],
)
def test_cli_gate_exit_status(monkeypatch, capsys, status, exit_code):
    from sidestory.market_talk import __main__ as cli

    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("MARKET_TALK_AUTO_ENABLED", "true")
    monkeypatch.setattr(cli, "connection", lambda: None)
    monkeypatch.setattr(cli, "TalkStore", lambda _: Store())
    monkeypatch.setattr(auto, "automatic_draft", lambda *a, **kw: {"status": status})
    assert cli.main(["--stage", "automate"]) == exit_code
