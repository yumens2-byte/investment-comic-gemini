"""Preserve content review evidence; default to advisory assembly/publication QC."""
import hashlib
import re
from pathlib import Path

from engine.publish.manifest import script_hash
from engine.quality.contracts import QualityHold
from engine.quality.policy import advisory_qc

PREFIX = "CONTENT_QC_HOLD:"


def _require_content_ready(script: dict, row: dict | None = None) -> None:
    if not isinstance(script, dict):
        raise QualityHold("content QC: malformed narrative")
    if row and str(row.get("error_message") or "").startswith(PREFIX):
        reason = str(row["error_message"])[len(PREFIX):].strip()
        reason = " ".join(reason.split())[:500] or "review required"
        raise QualityHold(
            f"content QC hold: {reason}; repair and review before assembly/publication"
        )
    if "_recovery_qc" not in script:
        return  # Existing episodes without a recovery review retain their contract.
    qc = script["_recovery_qc"]
    revision = script.get("_generation_revision", 1)
    if (not isinstance(qc, dict) or qc.get("version") != "content-qc-1"
            or qc.get("status") != "PASS"
            or qc.get("script_hash") != script_hash(script)
            or type(revision) is not int or not 1 <= revision <= 100
            or type(qc.get("generation_revision")) is not int
            or qc["generation_revision"] != revision):
        raise QualityHold("content QC hold: review missing, failed or stale")
    required = {str(p["idx"]) for p in script.get("panels", [])
                if p.get("panel_type") not in {"TEXT_CARD", "DISCLAIMER"}}
    hashes = qc.get("panel_hashes")
    if (not isinstance(hashes, dict) or set(hashes) != required
            or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h)
                   for h in hashes.values())):
        raise QualityHold("content QC hold: reviewed panel hashes missing")
    if row is not None:
        assets = row.get("panels_json")
        if not isinstance(assets, list):
            raise QualityHold("content QC hold: reviewed panel metadata missing")
        actual = {}
        for p in assets:
            if not isinstance(p, dict):
                raise QualityHold("content QC hold: malformed panel metadata")
            idx = str(p.get("panel_idx"))
            if idx in required:
                if idx in actual:
                    raise QualityHold("content QC hold: duplicate panel metadata")
                actual[idx] = p.get("sha256")
        if actual != hashes:
            raise QualityHold("content QC hold: reviewed panel identity changed")


def content_qc_findings(script: dict, row: dict | None = None) -> list[str]:
    """Pure inspection for preflight; preserves failed QC evidence without writes."""
    try:
        _require_content_ready(script, row)
    except QualityHold as exc:
        return [str(exc)]
    return []


@advisory_qc("content_review")
def require_content_ready(script: dict, row: dict | None = None) -> None:
    _require_content_ready(script, row)


@advisory_qc("reviewed_sources")
def require_reviewed_sources(script: dict, images: list[Path | None]) -> None:
    _require_content_ready(script)
    if "_recovery_qc" not in script:
        return
    hashes = script["_recovery_qc"]["panel_hashes"]
    for idx, expected in hashes.items():
        try:
            source = images[int(idx) - 1]
            actual = hashlib.sha256(source.read_bytes()).hexdigest() if source else None
        except (IndexError, OSError) as exc:
            raise QualityHold("content QC hold: reviewed source unavailable") from exc
        if actual != expected:
            raise QualityHold("content QC hold: reviewed source bytes changed")
