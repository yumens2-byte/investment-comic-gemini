"""Side episode status machine (P1 §1).

draft → narrative_done → image_done → assembled  (P2+: publishing → published)
Any gate failure → hold (error_message). A hold is resumed only on explicit request,
from the furthest stage whose artifact is stored.
"""
from __future__ import annotations

from typing import Any

P1_FLOW = ("draft", "narrative_done", "image_done", "assembled")
# stage name → (required status before, status after)
STAGE_TRANSITIONS = {
    "narrative": ("draft", "narrative_done"),
    "image": ("narrative_done", "image_done"),
    "assembly": ("image_done", "assembled"),
}
P1_STAGE_ORDER = ("narrative", "image", "assembly")


class TransitionError(RuntimeError):
    pass


def check_transition(stage: str, current: str) -> None:
    required, _ = STAGE_TRANSITIONS[stage]
    if current != required:
        raise TransitionError(f"stage {stage} requires status {required!r} (current {current!r})")


def target_status(stage: str) -> str:
    return STAGE_TRANSITIONS[stage][1]


def resume_status(row: dict[str, Any]) -> str:
    """Status to restore a held episode to, based on which artifacts exist."""
    if row.get("slides_json") and row.get("manifest_json"):
        return "assembled"
    if row.get("panels_json"):
        return "image_done"
    if row.get("script_json"):
        return "narrative_done"
    return "draft"


def remaining_stages(status: str) -> list[str]:
    """Stages still to run for p1 from the given status (empty when assembled)."""
    if status not in P1_FLOW:
        raise TransitionError(f"status {status!r} is not resumable by p1")
    done = P1_FLOW.index(status)
    return list(P1_STAGE_ORDER[done:])
