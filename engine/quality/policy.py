"""Advisory content QC. Operational errors and paid-call guards stay exceptions."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

logger = logging.getLogger(__name__)


def qc_is_strict() -> bool:
    mode = os.environ.get("ICG_QC_MODE", "warning").strip().lower()
    if mode not in {"warning", "strict"}:
        raise ValueError("ICG_QC_MODE must be warning or strict")
    return mode == "strict"


def qc_finding(gate: str, message: str, *, error_type=ValueError) -> None:
    if qc_is_strict():
        raise error_type(message)
    message = " ".join(str(message).split())[:1200]
    logger.warning("[QC_WARNING] %s: %s; continuing", gate, message)
    # Read-only/dry inspections never write or send QC alerts.
    if os.environ.get("DRY_RUN", "false").strip().lower() == "true":
        return
    record = {"ts": datetime.now(timezone.utc).isoformat(), "gate": gate,
              "message": message, "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
    try:
        path = Path("output/qc_warnings.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("QC alert journal unavailable; warning remains in execution log")


def advisory_qc(gate: str):
    """Only downgrade declared content findings, never unrelated exceptions."""
    def decorate(function):
        @wraps(function)
        def checked(*args, **kwargs):
            from engine.quality.contracts import QualityHold

            try:
                return function(*args, **kwargs)
            except QualityHold as exc:
                qc_finding(gate, str(exc), error_type=QualityHold)
                return None
        return checked
    return decorate
