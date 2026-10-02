"""Content review findings are warnings; delivery and asset validity remain separate."""
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from engine.publish.manifest import script_hash
from engine.quality.contracts import QualityHold

PREFIX = "CONTENT_QC_HOLD:"


def _check_content_ready(script: dict, row: dict | None = None) -> None:
    if not isinstance(script, dict):
        raise QualityHold("content QC: malformed narrative")
    if row and str(row.get("error_message") or "").startswith(PREFIX):
        raise QualityHold("content QC hold: repair and review before assembly/publication")
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


def _check_reviewed_sources(script: dict, images: list[Path | None]) -> None:
    _check_content_ready(script)
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


logger = logging.getLogger(__name__)
WARNING_PATH = Path("output/content-qc-warnings.jsonl")


def _record_warning(message: str, script: dict, row: dict | None = None) -> list[str]:
    """Never record a failed review as PASS and never let notification I/O stop work."""
    record = {"code": "CONTENT_QC_WARNING", "message": message,
              "episode_id": script.get("episode_id") or (row or {}).get("episode_date"),
              "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
    logger.warning("CONTENT_QC_WARNING: %s", message)
    try:
        WARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
        with WARNING_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("CONTENT_QC_WARNING: warning evidence write failed")
    return [message]


def require_content_ready(script: dict, row: dict | None = None) -> list[str]:
    if not isinstance(script, dict):
        raise ValueError("Malformed narrative: expected an object")
    try:
        _check_content_ready(script, row)
    except QualityHold as exc:
        return _record_warning(str(exc), script, row)
    return []


def require_reviewed_sources(script: dict, images: list[Path | None]) -> list[str]:
    if not isinstance(script, dict):
        raise ValueError("Malformed narrative: expected an object")
    try:
        _check_reviewed_sources(script, images)
    except QualityHold as exc:
        return _record_warning(str(exc), script)
    return []
