"""Pilot publication must honor episode holds and valid external receipts."""
import runpy
from pathlib import Path

import pytest

from engine.quality.contracts import QualityHold
from engine.quality.ledger import PilotLedger
from engine.quality.pipeline import business_status, publish_pilot

_helpers = runpy.run_path(str(Path(__file__).with_name("test_webtoon_quality.py")))

@pytest.fixture
def reviewed(tmp_path):
    fixture = _helpers["fixture"].__wrapped__(tmp_path)
    inputs, parts, report, release = _helpers["reviewed_release"](fixture)
    ledger = PilotLedger(tmp_path / "ledger.sqlite")
    return dict(ledger=ledger, root=fixture["root"], inputs=inputs, parts=parts,
                report=report, release=release)

@pytest.mark.parametrize("state", ["reserved", "unknown", "over_budget"])
def test_unsettled_cost_prevents_any_delivery(reviewed, state):
    ledger = reviewed["ledger"]
    call = ledger.reserve(episode=reviewed["release"].episode_id, kind="image", panel=1,
                          **_helpers["LIMITS"])
    if state == "unknown":
        ledger.settle(call, None)
    elif state == "over_budget":
        with pytest.raises(QualityHold):
            ledger.settle(call, ".2")
    sent = []
    with pytest.raises(QualityHold, match="reconciliation before publication"):
        publish_pilot(**reviewed, sender=lambda *args: sent.append(args) or "receipt")
    assert not sent
    assert not ledger.snapshot()["jobs"]

@pytest.mark.parametrize("receipt", [True, False, {}, [], "", "   ", "None", "null", 0])
def test_invalid_delivery_receipt_is_unknown_not_published(reviewed, receipt):
    with pytest.raises(QualityHold, match="ambiguous result"):
        publish_pilot(**reviewed, sender=lambda *args: receipt)
    assert reviewed["ledger"].snapshot()["jobs"][0]["state"] == "unknown"


def test_other_episode_hold_does_not_block_completed_episode(reviewed):
    ledger = reviewed["ledger"]
    ledger.reserve(episode="unrelated", kind="image", panel=1, **_helpers["LIMITS"])
    publish_pilot(**reviewed, sender=lambda c, i, p: f"{c}-{i}")
    release = reviewed["release"]
    keys = [f"{release.episode_id}:{release.release_version}:x:1"]
    assert business_status(ledger, keys)["status"] == "complete"
    assert business_status(ledger, keys, episode="unrelated")["status"] == "hold"


def test_generation_never_overwrites_output_created_during_provider_call(tmp_path):
    from io import BytesIO

    from PIL import Image

    from engine.quality.pipeline import generate_bounded

    reference = tmp_path / "reference.png"
    Image.new("RGB", (20, 20)).save(reference)
    output = tmp_path / "output.png"
    image = BytesIO()
    Image.new("RGB", (20, 20)).save(image, format="PNG")

    def provider(*args):
        output.write_bytes(b"another worker output")
        return image.getvalue(), ".05"

    with pytest.raises(QualityHold, match="concurrent output creation"):
        generate_bounded(ledger=PilotLedger(tmp_path / "ledger.sqlite"), episode="e",
                         panel=1, prompt="hero", refs=(reference,), output=output,
                         provider=provider, limits=_helpers["LIMITS"])
    assert output.read_bytes() == b"another worker output"
