"""Durable production reservations, without network or provider spending."""
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.image import generation_guard as module
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard


@pytest.fixture
def rpc(monkeypatch):
    client = Mock()
    client.schema.return_value = client
    response = {"data": {}}
    client.rpc.return_value.execute.side_effect = lambda: SimpleNamespace(data=response["data"])
    monkeypatch.setattr(module, "get_client", lambda: client)
    monkeypatch.setattr(module, "get_schema", lambda: "icg")
    return client, response


def guard(tmp_path, scope="output/episodes/2026-10-01/panels", prompt="hero"):
    ref = tmp_path / "ref.png"
    if not ref.exists():
        ref.write_bytes(b"reference")
    return ProductionGenerationGuard(scope=scope, panel=1, prompt=prompt, refs=[ref])


def test_runner_independent_identity(tmp_path):
    first = guard(tmp_path, "/runner/a/output/episodes/2026-10-01/panels")
    second = guard(tmp_path, "/runner/b/output/episodes/2026-10-01/panels")
    assert first._identity() == second._identity()
    assert first.scope == "output/episodes/2026-10-01/panels"


def test_windows_runner_identity_matches_posix(tmp_path):
    windows = guard(tmp_path, r"C:\runner\output\episodes\2026-10-01\panels")
    posix = guard(tmp_path, "/runner/output/episodes/2026-10-01/panels")
    assert windows._identity() == posix._identity()


def test_prompt_and_ref_changes_change_fingerprint(tmp_path):
    original = guard(tmp_path)
    assert original.fingerprint != guard(tmp_path, prompt="villain").fingerprint
    (tmp_path / "ref.png").write_bytes(b"changed")
    assert original.fingerprint != guard(tmp_path).fingerprint


@pytest.mark.parametrize("scope", ["", "../output/a", "/runner/unknown"])
def test_invalid_scope_holds(tmp_path, scope):
    with pytest.raises(GenerationHold):
        guard(tmp_path, scope)


def test_missing_ref_holds(tmp_path):
    with pytest.raises(GenerationHold):
        ProductionGenerationGuard(scope="output/a", panel=1, prompt="hero", refs=[tmp_path / "missing"])


def test_fresh_panel_false(rpc, tmp_path):
    instance = guard(tmp_path)
    assert instance.reuse(tmp_path / "P1.png") is False
    assert rpc[0].rpc.call_args.args[0] == "image_generation_inspect"


def test_success_reuse_validates_hash(rpc, tmp_path):
    instance = guard(tmp_path)
    path = tmp_path / "P1.png"
    path.write_bytes(b"success image")
    rpc[1]["data"] = {"output_hash": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert instance.reuse(path) is True
    path.write_bytes(b"changed")
    with pytest.raises(GenerationHold):
        instance.reuse(path)


def test_missing_success_artifact_does_not_regenerate(rpc, tmp_path):
    rpc[1]["data"] = {"output_hash": "0" * 64}
    with pytest.raises(GenerationHold):
        guard(tmp_path).reuse(tmp_path / "missing")


def test_unreceipted_artifact_holds(rpc, tmp_path):
    path = tmp_path / "P1.png"
    path.write_bytes(b"unreceipted")
    with pytest.raises(GenerationHold):
        guard(tmp_path).reuse(path)


@pytest.mark.parametrize("data", [None, [], "invalid", {"hold": "budget limit"}])
def test_invalid_or_hold_receipt_fail_closed(rpc, tmp_path, data):
    rpc[1]["data"] = data
    with pytest.raises(GenerationHold):
        guard(tmp_path).reuse(tmp_path / "P1.png")


def test_backend_error_fail_closed(rpc, tmp_path):
    rpc[0].rpc.side_effect = RuntimeError("database down")
    with pytest.raises(GenerationHold):
        guard(tmp_path).reserve()


@pytest.mark.parametrize("token", [None, "", 123])
def test_missing_or_invalid_token_holds(rpc, tmp_path, token):
    rpc[1]["data"] = {"token": token}
    with pytest.raises(GenerationHold):
        guard(tmp_path).reserve()


def test_valid_reservation(rpc, tmp_path):
    rpc[1]["data"] = {"token": "uuid-reservation"}
    assert guard(tmp_path).reserve() == "uuid-reservation"


@pytest.mark.parametrize("cost", [-0.01, float("inf"), float("nan")])
def test_invalid_cost_keeps_reservation_held(rpc, tmp_path, cost):
    with pytest.raises(GenerationHold):
        guard(tmp_path).finish("token", state="success", actual_cost=cost, output_hash="abc")
    rpc[0].rpc.assert_not_called()


def test_unknown_cost_durable_hold(rpc, tmp_path):
    rpc[1]["data"] = {"hold": "unknown billing"}
    with pytest.raises(GenerationHold):
        guard(tmp_path).finish("token", state="success", actual_cost=None, output_hash="a" * 64)
    params = rpc[0].rpc.call_args.args[1]
    assert params["p_actual_cost"] is None
    assert params["p_output_hash"] == "a" * 64


def test_success_cost_and_hash_durable(rpc, tmp_path):
    rpc[1]["data"] = {"settled": True}
    guard(tmp_path).finish("token", state="success", actual_cost=0.04, output_hash="a" * 64)
    assert rpc[0].rpc.call_args.args[0] == "image_generation_finish"
    assert rpc[0].rpc.call_args.args[1]["p_actual_cost"] == 0.04


def test_unconfirmed_finish_holds(rpc, tmp_path):
    with pytest.raises(GenerationHold):
        guard(tmp_path).finish("token", state="success", actual_cost=0.04, output_hash="a" * 64)
