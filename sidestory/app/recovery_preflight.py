"""Read-only safety assessment of an existing Sidestory episode.

This command does NOT reconcile provider charges, unlock HOLD, create images,
or publish. A successful diagnostic run is not approval for a paid retry.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from sidestory.app.pipeline import side_episode_id
from sidestory.ports.store import SideStore

BLOCKED_STATES = frozenset({"reserved", "unknown", "terminal"})


def _file_hash(path: Path) -> str | None:
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def check_recovery(
    side_day: date, store: SideStore, *,
    output_root: Path = Path("output/sidestory"),
) -> dict[str, Any]:
    """Inspect only. Never infer that UNKNOWN means unbilled or failed."""
    sid = side_episode_id(side_day)
    day_root = output_root / side_day.isoformat()
    scopes = [(day_root / "panels").as_posix(),
              (day_root / "v2" / "panels").as_posix()]

    row = store.get_episode(sid)
    # Consult BOTH paid-call scopes even when the episode or publication row is absent.
    blockers: list[dict[str, Any]] = []
    for scope in scopes:
        for entry in store.image_ledger_blockers(scope):
            state = str(entry.get("state") or "")
            if state not in BLOCKED_STATES:
                # Treat an unexpected adapter response as unsafe, never as cleared.
                state = "invalid_ledger_state"
            blockers.append({"scope": scope, "panel": entry.get("panel"),
                             "state": state, "created_at": entry.get("created_at")})
    live_publication = store.live_publication(sid, "facebook")
    checkpoint = (row or {}).get("panels_json") or {}
    panels = checkpoint.get("panels") or []
    verified_panels: list[int] = []
    invalid_panels: list[int] = []
    for entry in panels:
        panel_id = entry.get("idx")
        expected = entry.get("sha256")
        path = entry.get("path")
        if isinstance(panel_id, int) and isinstance(expected, str) and isinstance(path, str):
            valid = len(expected) == 64 and _file_hash(Path(path)) == expected
        else:
            valid = False
        (verified_panels if valid else invalid_panels).append(panel_id)

    if blockers:
        status = "BLOCKED_LEDGER_RECONCILIATION"
        next_action = "Obtain provider billing/outcome evidence; keep UNKNOWN and HOLD unchanged."
    elif live_publication or (row and row.get("status") == "published"):
        status = "ALREADY_PUBLISHED"
        next_action = "Verify external Facebook receipt; do not post a duplicate."
    elif row is None:
        status = "NO_EPISODE"
        next_action = "Investigate missing episode; no paid work is authorized by this report."
    elif invalid_panels:
        status = "BLOCKED_ARTIFACT_RESTORATION"
        next_action = "Restore existing paid panel artifacts and verify SHA-256; do not regenerate."
    elif row.get("status") == "hold":
        status = "OPERATOR_REVIEW_REQUIRED"
        next_action = "Verify documented reconciliation and approve separate HOLD recovery."
    else:
        status = "OPERATOR_REVIEW_REQUIRED"
        next_action = "Review current stage and publication controls before any paid action."

    return {
        "stage": "recovery_check",
        "side_episode_id": sid,
        "date": side_day.isoformat(),
        "status": status,
        "read_only": True,
        "may_retry_paid": False,
        "may_publish": False,
        "episode_status": (row or {}).get("status"),
        "has_script": bool((row or {}).get("script_json")),
        "has_slides": bool((row or {}).get("slides_json")),
        "has_live_publication": bool(live_publication),
        "ledger_blockers": blockers,
        "verified_checkpoint_panels": sorted(verified_panels),
        "invalid_checkpoint_panels": sorted(invalid_panels),
        "checkpoint_run_id": checkpoint.get("run_id"),
        "next_action": next_action,
    }
