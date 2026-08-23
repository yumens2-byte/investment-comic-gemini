"""Regression coverage for Anthropic SDK messages.create compatibility."""

from engine.narrative.claude_client import _build_messages_create_kwargs


def _inputs(method) -> dict:
    return _build_messages_create_kwargs(
        method,
        model="test-model",
        system_prompt="system",
        messages=[{"role": "user", "content": "hello"}],
    )


def test_current_sdk_signature_does_not_receive_removed_temperature() -> None:
    from anthropic import Anthropic

    create = Anthropic(api_key="test").messages.create

    assert "temperature" not in _inputs(create)


def test_legacy_sdk_signature_keeps_configured_temperature() -> None:
    def legacy_create(*, model, max_tokens, system, messages, temperature):
        return None

    kwargs = _inputs(legacy_create)

    assert kwargs["temperature"] == 0.7


def test_generic_mock_signature_keeps_backward_compatibility() -> None:
    def proxy_create(**kwargs):
        return kwargs

    assert _inputs(proxy_create)["temperature"] == 0.7
