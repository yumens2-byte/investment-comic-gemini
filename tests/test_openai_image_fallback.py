"""OpenAI final fallback after Gemini quota exhaustion, using no paid requests."""
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai import errors as genai_errors
from PIL import Image

from engine.image import gemini_client as adapter
from engine.image import openai_client as oa
from engine.image.generation_guard import GenerationHold


def png(size=(4, 4), color="red"):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def genai_error(code, status, message="Quota exceeded"):
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"code": code, "status": status, "message": message}})


def guard_mock():
    guard = Mock()
    guard.reuse.return_value = False
    guard.reserve.side_effect = [f"r{i}" for i in range(1, 10)]
    return guard


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ICG_IMAGE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "false")
    monkeypatch.delenv("ICG_OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("ICG_OPENAI_IMAGE_QUALITY", raising=False)
    monkeypatch.setattr(adapter, "_get_client", lambda: Mock())
    gemini = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, "_generate_one", gemini)
    openai_call = Mock(return_value=(png(color="blue"), 0.05))
    monkeypatch.setattr(oa, "generate_one", openai_call)
    monkeypatch.setattr(oa, "_get_client", lambda: Mock())
    ref = tmp_path / "hero.png"
    ref.write_bytes(png())
    out = tmp_path / "output" / "episodes" / "2026-10-28" / "panels"
    return SimpleNamespace(gemini=gemini, openai=openai_call, ref=ref, out=out, root=tmp_path)


def run_panel(env, guard, idx=1, state=None, aspect=None):
    state = state if state is not None else adapter.ProviderState(env.out)
    return adapter.generate_panel(idx, "hero and villain", [env.ref], env.out, env.out / "run.log",
                                  aspect_ratio=aspect, guard=guard, provider_state=state), state


def states(guard):
    return [(c.kwargs["state"], c.kwargs["actual_cost"]) for c in guard.finish.call_args_list]


@pytest.mark.parametrize("exc", [
    genai_error(429, "RESOURCE_EXHAUSTED"),
    genai_error(403, "PERMISSION_DENIED", "Billing account has no prepay credit"),
    genai_error(400, "FAILED_PRECONDITION", "billing is not enabled"),
])
def test_gemini_quota_settles_zero_and_same_panel_continues_on_openai(env, exc):
    env.gemini.side_effect = exc
    guard = guard_mock()
    (path, cost), state = run_panel(env, guard)
    assert path.read_bytes() == png(color="blue")
    assert cost == pytest.approx(0.05)
    assert env.gemini.call_count == 1 and env.openai.call_count == 1
    assert states(guard) == [("failed", 0.0), ("success", 0.05)]
    assert state.active == "openai"
    assert state.fallback["from_panel"] == 1 and state.fallback["reason"] == "QUOTA_EXHAUSTED"
    saved = json.loads((env.out / "image-providers.json").read_text())
    assert saved["panels"]["1"]["provider"] == "openai"
    log = [json.loads(line) for line in (env.out / "run.log").read_text().splitlines()]
    assert [r["status"] for r in log] == ["quota_exhausted", "success"]
    assert log[0]["provider_status"] == exc.status
    assert guard.store_attempt_diagnostic.call_args_list[1].args[1] == "refusal"
    openai_inputs = guard.store_attempt_diagnostic.call_args_list[2].args[2]
    assert openai_inputs["provider"] == "openai" and openai_inputs["model"] == "gpt-image-2"


@pytest.mark.parametrize("exc", [
    genai_error(401, "UNAUTHENTICATED", "API key invalid"),
    genai_error(400, "INVALID_ARGUMENT", "bad request"),
    genai_error(403, "PERMISSION_DENIED", "caller does not have permission"),
    genai_error(500, "INTERNAL", "backend error"),
    RuntimeError("quota exhausted"),
])
def test_non_quota_errors_keep_existing_hold(env, exc):
    env.gemini.side_effect = exc
    guard = guard_mock()
    with pytest.raises(GenerationHold, match="Provider outcome requires reconciliation"):
        run_panel(env, guard)
    assert env.openai.call_count == 0
    assert states(guard)[0][1] is None


@pytest.mark.parametrize("setting", [("ICG_IMAGE_OPENAI_FALLBACK_ENABLED", "false"),
                                     ("OPENAI_API_KEY", "")])
def test_disabled_or_unkeyed_fallback_keeps_existing_hold(env, monkeypatch, setting):
    monkeypatch.setenv(*setting)
    env.gemini.side_effect = genai_error(429, "RESOURCE_EXHAUSTED")
    guard = guard_mock()
    with pytest.raises(GenerationHold):
        run_panel(env, guard)
    assert env.openai.call_count == 0
    assert states(guard) == [("terminal", None)]


def test_without_provider_state_quota_is_unchanged(env):
    env.gemini.side_effect = genai_error(429, "RESOURCE_EXHAUSTED")
    guard = guard_mock()
    with pytest.raises(GenerationHold):
        adapter.generate_panel(1, "hero", [env.ref], env.out, env.out / "run.log", guard=guard)
    assert env.openai.call_count == 0


def test_episode_continues_remaining_panels_on_openai_with_gemini_anchor(env, monkeypatch):
    env.gemini.side_effect = [(png(size=(8, 10)), 100, 1290), genai_error(429, "RESOURCE_EXHAUSTED")]
    env.openai.return_value = (png(size=(16, 20), color="blue"), 0.05)
    guards = [guard_mock() for _ in range(3)]
    monkeypatch.setattr(adapter, "ProductionGenerationGuard", Mock(side_effect=guards))
    panels = [{"panel_idx": i, "prompt_text": f"panel {i}", "ref_image_paths": [env.ref],
               "aspect_ratio": "4:5"} for i in (1, 2, 3)]
    paths, cost = adapter.generate_episode(panels, env.out)
    assert all(paths)
    assert env.gemini.call_count == 2  # P1 success, P2 quota; never called for P3
    assert env.openai.call_count == 2
    anchor = env.out / "P1.png"
    assert all(c.args[3] == anchor for c in env.openai.call_args_list)
    assert all(c.args[4] == "4:5" for c in env.openai.call_args_list)
    # OpenAI output is normalized to the Gemini anchor's pixel size.
    assert Image.open(env.out / "P3.png").size == (8, 10)
    summary = json.loads((env.out / "generation-summary.json").read_text())
    assert summary["provider_by_panel"] == {"1": "gemini", "2": "openai", "3": "openai"}
    assert summary["image_provider_fallback"]["style_anchor_sha256"] == hashlib.sha256(
        anchor.read_bytes()).hexdigest()
    assert summary["complete"] is True
    assert cost == pytest.approx(adapter._calc_cost(100, 1290) + 0.10)


def test_rerun_resumes_on_openai_and_verifies_anchor(env):
    state = adapter.ProviderState(env.out)
    env.out.mkdir(parents=True, exist_ok=True)
    (env.out / "P1.png").write_bytes(png())
    state.switch(2, "QUOTA_EXHAUSTED")
    resumed = adapter.ProviderState(env.out)
    assert resumed.active == "openai" and resumed.style_anchor == env.out / "P1.png"
    run_panel(env, guard_mock(), idx=2, state=resumed)
    assert env.gemini.call_count == 0 and env.openai.call_count == 1
    (env.out / "P1.png").write_bytes(png(color="green"))
    with pytest.raises(GenerationHold, match="style anchor changed"):
        adapter.ProviderState(env.out)


def test_openai_anchor_skips_openai_panels_and_uses_asset(env):
    env.out.mkdir(parents=True)
    state = adapter.ProviderState(env.out)
    (env.out / "P1.png").write_bytes(png())
    state.record(1, env.out / "P1.png", "openai", "gpt-image-2")
    assert state._choose_anchor(2) is None
    asset = env.root / oa.STYLE_ANCHOR_ASSET
    asset.parent.mkdir(parents=True)
    asset.write_bytes(png())
    assert state._choose_anchor(2) == oa.STYLE_ANCHOR_ASSET


def switched_state(env):
    state = adapter.ProviderState(env.out)
    state.switch(1, "QUOTA_EXHAUSTED")
    return state


def test_openai_quota_holds_as_providers_exhausted(env):
    env.openai.side_effect = oa.OpenAIQuotaExhausted("OpenAI 429")
    guard = guard_mock()
    with pytest.raises(GenerationHold, match="IMAGE_PROVIDERS_EXHAUSTED"):
        run_panel(env, guard, state=switched_state(env))
    assert states(guard) == [("failed", 0.0)]


def test_openai_terminal_holds(env):
    env.openai.side_effect = oa.OpenAITerminal("OpenAI AuthenticationError")
    guard = guard_mock()
    with pytest.raises(GenerationHold, match="OpenAI fallback rejected"):
        run_panel(env, guard, state=switched_state(env))
    assert states(guard) == [("terminal", 0.0)]


@pytest.mark.parametrize("exc", [oa.OpenAIRefusal("moderation_blocked"), TimeoutError("timeout")])
def test_openai_refusal_or_ambiguous_outcome_is_unknown_hold(env, exc):
    env.openai.side_effect = exc
    guard = guard_mock()
    with pytest.raises(GenerationHold, match="provider=openai"):
        run_panel(env, guard, state=switched_state(env))
    assert states(guard) == [("unknown", None)]
    assert env.openai.call_count == 1


def test_openai_missing_usage_is_never_settled_as_measured(env):
    env.openai.return_value = (png(), None)
    guard = guard_mock()
    (path, cost), _ = run_panel(env, guard, state=switched_state(env))
    assert states(guard) == [("success", None)]
    assert cost == pytest.approx(0.10)


def test_openai_invalid_image_is_settled_and_retried(env):
    env.openai.side_effect = [(b"not png", 0.04), (png(), 0.05)]
    guard = guard_mock()
    (path, cost), _ = run_panel(env, guard, state=switched_state(env))
    assert path is not None and cost == pytest.approx(0.09)
    assert states(guard) == [("failed", 0.04), ("success", 0.05)]


def test_input_limits_hold_before_reservation(env):
    guard = guard_mock()
    refs = []
    for i in range(16):
        ref = env.root / f"r{i}.png"
        ref.write_bytes(png())
        refs.append(ref)
    state = adapter.ProviderState(env.out)
    env.out.mkdir(parents=True, exist_ok=True)
    (env.out / "P1.png").write_bytes(png())
    state.switch(2, "QUOTA_EXHAUSTED")
    with pytest.raises(GenerationHold, match="input images 17"):
        adapter.generate_panel(2, "x", refs, env.out, env.out / "run.log",
                               guard=guard, provider_state=state)
    guard.reserve.assert_not_called()


def test_unsupported_aspect_holds_before_reservation(env):
    guard = guard_mock()
    with pytest.raises(GenerationHold, match="aspect ratio 9:16"):
        run_panel(env, guard, state=switched_state(env), aspect="9:16")
    guard.reserve.assert_not_called()


def test_cost_sizes_prompt_and_settings(monkeypatch):
    usage = {"input_tokens": 1500, "output_tokens": 1000,
             "input_tokens_details": {"text_tokens": 500, "image_tokens": 1000}}
    assert oa.calc_cost(usage) == pytest.approx((500 * 8 + 1000 * 8 + 1000 * 30) / 1e6)
    monkeypatch.setenv("ICG_OPENAI_COST_TEXT_IN_PER_1M", "5")
    assert oa.calc_cost(usage) == pytest.approx((500 * 5 + 1000 * 8 + 1000 * 30) / 1e6)
    assert oa.calc_cost(None) is None
    assert oa.calc_cost({"input_tokens": 0, "output_tokens": 0}) is None
    assert oa.size_for("4:5") == "1024x1280" and oa.size_for(None) == "1024x1024"
    assert oa.build_prompt("P", 2, True).startswith("INPUT IMAGES: images 1..2")
    assert "STYLE REFERENCE ONLY" in oa.build_prompt("P", 0, True)
    assert "STYLE LOCK" in oa.build_prompt("P", 2, False)
    monkeypatch.setenv("ICG_OPENAI_IMAGE_MODEL", "gpt-image-1")
    with pytest.raises(GenerationHold):
        oa.model_name()
    monkeypatch.setenv("ICG_OPENAI_IMAGE_QUALITY", "max")
    with pytest.raises(GenerationHold):
        oa.quality_name()
    monkeypatch.setenv("ICG_IMAGE_OPENAI_FALLBACK_ENABLED", "yes")
    with pytest.raises(GenerationHold):
        oa.fallback_enabled()


def test_generate_one_maps_sdk_errors_and_decodes(tmp_path):
    import base64

    import httpx
    import openai

    ref = tmp_path / "hero.jpg"
    ref.write_bytes(png())
    client = Mock()
    client.images.edit.return_value = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(png()).decode())],
        usage={"input_tokens": 10, "output_tokens": 20})
    data, cost = oa.generate_one(client, "prompt", [ref], None, "4:5")
    assert data == png() and cost > 0
    kwargs = client.images.edit.call_args.kwargs
    assert kwargs["size"] == "1024x1280" and kwargs["quality"] == "medium"
    assert kwargs["image"][0][2] == "image/jpeg" and "input_fidelity" not in kwargs

    request = httpx.Request("POST", "https://api.openai.com/v1/images/edits")

    def status_error(cls, status, code):
        response = httpx.Response(status, request=request)
        return cls("error", response=response, body={"code": code})

    for error, expected in [
        (status_error(openai.RateLimitError, 429, "insufficient_quota"), oa.OpenAIQuotaExhausted),
        (status_error(openai.BadRequestError, 400, "moderation_blocked"), oa.OpenAIRefusal),
        (status_error(openai.BadRequestError, 400, "invalid_value"), oa.OpenAITerminal),
        (status_error(openai.AuthenticationError, 401, None), oa.OpenAITerminal),
    ]:
        client.images.edit.side_effect = error
        with pytest.raises(expected):
            oa.generate_one(client, "prompt", [ref], None, None)
    client.images.edit.side_effect = None
    client.images.edit.return_value = SimpleNamespace(data=[], usage=None)
    with pytest.raises(oa.OpenAINoImage):
        oa.generate_one(client, "prompt", [ref], None, None)


def test_outcome_v3_settlement_records_quota_reason(env, monkeypatch):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    env.gemini.side_effect = genai_error(429, "RESOURCE_EXHAUSTED")
    guard = guard_mock()
    run_panel(env, guard)
    first, second = guard.finish_outcome.call_args_list
    assert first.kwargs == {"state": "failed", "actual_cost": 0.0, "output_hash": None,
                            "reason": "QUOTA_EXHAUSTED"}
    assert second.kwargs["state"] == "success" and second.kwargs["actual_cost"] == 0.05


def test_quota_settlement_hold_never_calls_openai(env, monkeypatch):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    env.gemini.side_effect = genai_error(429, "RESOURCE_EXHAUSTED")
    guard = guard_mock()
    guard.finish_outcome.side_effect = GenerationHold("Settlement not confirmed")
    with pytest.raises(GenerationHold, match="quota settlement not confirmed"):
        run_panel(env, guard)
    assert env.openai.call_count == 0
