"""Offline-first quality preparation and bounded single-host pilot operations."""

from pathlib import Path
from typing import Callable

from engine.quality.canon import CanonManifest, verify_manifest
from engine.quality.contracts import (
    Claim,
    EditorialPlan,
    EvidenceBundle,
    QualityHold,
    digest,
    validate_claims,
    validate_plan,
)
from engine.quality.ledger import PilotLedger
from engine.quality.publish_guard import require_publication_id
from engine.quality.release import QualityReport, ReleaseManifest


def prepare(
    *,
    bundle: EvidenceBundle,
    plan: EditorialPlan,
    claims: list[Claim],
    canon: CanonManifest,
    script: dict,
    calculation: dict,
    root: Path,
) -> dict:
    """Validate source contracts before any paid call. Does not approve rendered art."""
    if not calculation.get("outcome"):
        raise QualityHold("deterministic calculation outcome missing")
    validate_plan(plan, bundle, script, calculation)
    validate_claims(bundle, claims, script["panels"])
    verify_manifest(canon, script, root)
    inputs = {
        "evidence": bundle.model_dump(mode="json"),
        "editorial": plan.model_dump(mode="json"),
        "claims": [c.model_dump(mode="json") for c in claims],
        "canon": canon.model_dump(mode="json"),
        "script": script,
        "calculation": calculation,
    }
    return {
        "inputs": inputs,
        "input_hashes": {k: digest(v) for k, v in inputs.items()},
        "status": "awaiting_images_and_human_review",
    }


def generate_bounded(
    *,
    ledger: PilotLedger,
    episode: str,
    panel: int,
    prompt: str,
    refs: tuple[Path, ...],
    output: Path,
    provider: Callable,
    limits: dict,
) -> Path:
    """Provider must make ONE attempt and return (image bytes, actual USD cost).

    Do not pass an SDK/tenacity wrapper with hidden retries. Unknown charges hold
    the episode until reconciled with provider usage. Successful panels are reused.
    """
    if output.exists():
        raise QualityHold("existing output requires explicit hash-verified reuse")
    if not refs or any(not p.is_file() for p in refs):
        raise QualityHold("all required references must exist")
    call_id = ledger.reserve(episode=episode, kind="image", panel=panel, **limits)
    try:
        image, cost = provider(prompt, refs)
    except Exception:
        ledger.settle(call_id, None, failed=True)
        raise
    ledger.settle(call_id, str(cost))
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(image)) as decoded:
        decoded.verify()
    with Image.open(BytesIO(image)) as decoded:
        decoded.load()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as destination:
            destination.write(image)
    except FileExistsError as exc:
        raise QualityHold("concurrent output creation requires hash-verified reuse") from exc
    ledger.event("image_completed", {"episode": episode, "panel": panel, "call_id": call_id})
    return output


def publish_pilot(
    *,
    ledger: PilotLedger,
    release: ReleaseManifest,
    root: Path,
    inputs: dict,
    report: QualityReport,
    parts: dict[str, list[dict]],
    sender: Callable,
    live: bool = False,
) -> dict:
    """Exercise part-level journals with an injected simulator. Never live SNS."""
    if live:
        raise QualityHold("SQLite pilot cannot coordinate production publishers")
    release.verify(root, inputs, report)
    if ledger.unsettled_calls(release.episode_id):
        raise QualityHold("unsettled provider call requires reconciliation before publication")
    if set(parts) != set(release.required_channels) or any(not v for v in parts.values()):
        raise QualityHold("all required channel parts must be declared")
    # Bind delivery payload as well as image artifacts to the approved inputs.
    if inputs.get("publication_parts") != parts:
        raise QualityHold("publication parts must be part of reviewed inputs")
    results = {}
    for channel in release.required_channels:
        results[channel] = []
        for index, part in enumerate(parts[channel], 1):
            if ledger.unsettled_calls(release.episode_id):
                raise QualityHold("unsettled provider call requires reconciliation before publication")
            key = f"{release.episode_id}:{release.release_version}:{channel}:{index}"
            token, previous = ledger.claim(
                key, digest({"release": release.content_hash, "part": part})
            )
            if token is None:
                results[channel].append(previous)
                continue
            try:
                external_id = require_publication_id(
                    {"id": sender(channel, index, part)}, "id"
                )
            except Exception as exc:
                ledger.finish(key, token, "unknown", detail=type(exc).__name__)
                ledger.event("publication_unknown", {"key": key})
                raise QualityHold("ambiguous result; reconcile before retry") from exc
            ledger.finish(key, token, "published", str(external_id))
            results[channel].append(str(external_id))
    ledger.event("pilot_published", {"episode": release.episode_id, "results": results})
    return results


def business_status(
    ledger: PilotLedger, expected_keys: list[str], *, episode: str | None = None
) -> dict:
    snapshot = ledger.snapshot()
    jobs = {j["key"]: j for j in snapshot["jobs"]}
    states = {key: jobs[key]["state"] if key in jobs else "missing" for key in expected_keys}
    episodes = {episode} if episode is not None else {key.rsplit(":", 3)[0] for key in expected_keys}
    unsettled = [
        c["id"] for c in snapshot["calls"]
        if c["episode"] in episodes and c["state"] in {"reserved", "unknown", "over_budget"}
    ]
    return {
        "status": (
            "complete"
            if states and not unsettled and all(s == "published" for s in states.values())
            else "hold"
        ),
        "parts": states,
        "unsettled_calls": unsettled,
    }
