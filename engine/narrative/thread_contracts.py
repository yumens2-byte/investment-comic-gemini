"""Evidence contracts; lexical reuse is progress, never proof of resolution."""
from __future__ import annotations

import hashlib
import json
import re

from engine.narrative.serial_contracts import normalize_thread

_UNRESOLVED = re.compile(r"여전히.*(모르|미해결)|아직.*(모르|미해결)|\b(unresolved|unknown)\b", re.I)


def review_fingerprint(script: dict) -> str:
    payload = {key: script.get(key) for key in
               ("panels", "thread_transitions", "resolved_threads", "unresolved_threads")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def previous_threads(previous: dict) -> dict[str, dict]:
    values = previous.get("structured_threads") or previous.get("unresolved_threads") or []
    result = {}
    for value in values:
        item = normalize_thread(value, source_episode_id=previous.get("source_episode_id", ""))
        if item["status"] not in {"PAID", "RESOLVED"}:
            result[item["thread_id"]] = item
    return result


_NON_EVIDENCE_PANEL_TYPES = {"DISCLAIMER", "TEXT_CARD"}


def _panel_map(script: dict) -> dict:
    return {p.get("idx"): p for p in script.get("panels", []) if isinstance(p, dict)}


def evidence_errors(item: dict, panels: dict) -> list[str]:
    """Evidence check shared by validation and deterministic downgrade.

    The quote must appear verbatim in the cited (post-trim, publishable) panel text.
    """
    errors: list[str] = []
    indices = item.get("evidence_panel_idxs") or []
    quote = str(item.get("evidence_quote") or "").strip()
    fact = str(item.get("new_fact") or "").strip()
    panel_text = "\n".join(str(panels[i].get(k) or "") for i in indices
                           if i in panels for k in ("narration", "key_text"))
    if not indices or any(i not in panels or panels[i].get("panel_type") in
                          _NON_EVIDENCE_PANEL_TYPES for i in indices):
        errors.append("thread_evidence_panel_missing")
    if not quote or quote not in panel_text or not fact:
        errors.append("thread_evidence_missing")
    return errors


def downgrade_unverified_progress(script: dict, previous: dict) -> list[dict]:
    """Downgrade PROGRESSED transitions without verifiable evidence to OPEN (in place).

    2026-10-05 gate rebalance: an unsupported *progress* claim is reverted to OPEN and
    audited instead of failing the episode. RESOLVED is never touched here; its
    evidence/review contract stays fail-closed in validate_thread_transitions.

    Ordering contract (CR-8): this mutates thread_transitions and therefore changes
    review_fingerprint(). Any independent _resolution_review must be produced AFTER
    this downgrade (run_market applies it right after generation, before any review).
    Returns the audit records appended to script["_thread_downgrades"].
    """
    threads = previous_threads(previous)
    panels = _panel_map(script)
    records: list[dict] = []
    for item in script.get("thread_transitions") or []:
        if not isinstance(item, dict) or item.get("status") != "PROGRESSED":
            continue
        if item.get("thread_id") not in threads:
            continue  # unknown IDs stay a hard contract error
        reasons = evidence_errors(item, panels)
        if not reasons:
            continue
        item["status"] = "OPEN"
        records.append({
            "thread_id": item.get("thread_id"),
            "from": "PROGRESSED",
            "to": "OPEN",
            "reasons": reasons,
            "evidence_panel_idxs": list(item.get("evidence_panel_idxs") or []),
            "evidence_quote": str(item.get("evidence_quote") or ""),
        })
    if records:
        script.setdefault("_thread_downgrades", []).extend(records)
    return records


def validate_thread_transitions(script: dict, previous: dict,
                                review: dict | None = None) -> list[str]:
    """A generated self-report cannot approve its own semantic resolution."""
    errors: list[str] = []
    threads = previous_threads(previous)
    panels = _panel_map(script)
    transitions = script.get("thread_transitions") or []
    seen: set[str] = set()
    resolved: list[str] = []
    for item in transitions:
        if not isinstance(item, dict):
            errors.append("invalid_thread_transition")
            continue
        thread_id = item.get("thread_id")
        if thread_id not in threads or thread_id in seen:
            errors.append("unknown_or_duplicate_thread")
            continue
        seen.add(thread_id)
        state = item.get("status")
        if state not in {"OPEN", "PROGRESSED", "RESOLVED"}:
            errors.append("invalid_thread_status")
            continue
        if state == "OPEN":
            continue
        quote = str(item.get("evidence_quote") or "").strip()
        errors.extend(evidence_errors(item, panels))
        if state != "RESOLVED":
            continue
        resolved.append(threads[thread_id]["promise"])
        result = str(item.get("resolution_result") or "").strip()
        if not result or _UNRESOLVED.search(result + " " + quote) or result == threads[thread_id]["promise"]:
            errors.append("false_thread_resolution")
        approval = (review or {}).get("resolutions", {}).get(thread_id)
        if ((review or {}).get("script_hash") != review_fingerprint(script)
                or not isinstance(approval, dict) or approval.get("status") != "PASS"
                or approval.get("evidence_quote") != quote):
            errors.append("thread_resolution_review_required")
    declarations = [str(x).strip() for x in script.get("resolved_threads") or []]
    if sorted(declarations) != sorted(resolved):
        errors.append("unverified_resolved_thread")
    return list(dict.fromkeys(errors))


def thread_prompt(previous: dict) -> str:
    threads = list(previous_threads(previous).values())
    return (
        "\n## Continuity contract v2 (authoritative schema extension)\n"
        "thread_transitions is an array of {thread_id, status, evidence_panel_idxs, "
        "evidence_quote, new_fact, resolution_result}. Use the supplied stable IDs.\n"
        "OPEN may carry an unanswered question; PROGRESSED requires an exact panel quote "
        "and a new fact. Copy evidence_quote verbatim from the cited panel narration "
        "(key_text may be shortened after generation). Use \"\" (never null) for unused "
        "text fields. Do not copy an unresolved sentence into resolved_threads.\n"
        "RESOLVED requires an independently reviewed actual answer. If no independent "
        "review is available, keep it OPEN/PROGRESSED and resolved_threads empty.\n"
        "Do not put transition objects in the legacy string arrays.\n"
        + json.dumps(threads, ensure_ascii=False)
    )
