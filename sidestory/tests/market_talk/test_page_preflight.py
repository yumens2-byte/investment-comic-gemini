"""Operational gate failures must be detected without uploading or reserving."""

from types import SimpleNamespace

import pytest

from sidestory.market_talk.diagnostics import DeliveryError
from sidestory.market_talk.publishing import ControlledPublisher
from sidestory.ports.publisher import PublishError


@pytest.mark.parametrize("phase", ["page_history", "page_gate_contract"])
def test_preflight_failure_is_read_only_and_redacted(phase):
    calls = []

    def fail(*args):
        raise PublishError("secret-token https://provider.invalid/?access_token=secret-token")

    provider = SimpleNamespace(
        check=lambda: {"id": "123"},
        recent_receipts=fail if phase == "page_history" else lambda _: [],
        upload_photo=lambda _: calls.append("upload"),
        create_post=lambda *args: calls.append("post"),
    )
    store = SimpleNamespace(
        require_hardening=fail if phase == "page_gate_contract" else lambda: None,
        observe=lambda *args: calls.append("observe"),
        begin=lambda *args: calls.append("begin"),
    )
    pub = ControlledPublisher(provider, store, "123", "key", "sidestory")
    with pytest.raises(DeliveryError) as error:
        pub.check()
    assert error.value.phase == phase
    assert "secret-token" not in str(error.value)
    assert calls == []


@pytest.mark.parametrize("phase", ["page_gate_observe", "page_gate_begin"])
def test_send_gate_failure_names_phase_without_posting(phase):
    calls = []

    def fail(*args):
        raise RuntimeError("private DB detail")

    provider = SimpleNamespace(
        recent_receipts=lambda _: [], create_post=lambda *args: calls.append("post")
    )
    store = SimpleNamespace(
        observe=fail if phase == "page_gate_observe" else lambda *args: None,
        begin=fail,
    )
    with pytest.raises(DeliveryError) as error:
        ControlledPublisher(provider, store, "123", "key", "sidestory").create_post("body", [])
    assert error.value.phase == phase
    assert "private" not in str(error.value)
    assert calls == []


def test_successful_preflight_still_rechecks_history_at_send():
    calls = []
    provider = SimpleNamespace(
        check=lambda: {"id": "123"},
        recent_receipts=lambda _: calls.append("history") or [],
        create_post=lambda *args: calls.append("post") or "123_1",
    )
    store = SimpleNamespace(
        require_hardening=lambda: calls.append("contract"),
        observe=lambda *args: calls.append("observe"),
        begin=lambda *args: calls.append("begin") or {"status": "SENDING", "token": "t"},
        finish=lambda *args, **kwargs: calls.append("finish"),
    )
    pub = ControlledPublisher(provider, store, "123", "key", "sidestory")
    assert pub.check() == {"id": "123"}
    assert calls == ["history", "contract"]
    assert pub.create_post("body", []) == "123_1"
    assert calls == ["history", "contract", "history", "observe", "begin", "post", "finish"]
