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


def validate_thread_transitions(script: dict, previous: dict,
                                review: dict | None = None) -> list[str]:
    """A generated self-report cannot approve its own semantic resolution."""
    errors: list[str] = []
    threads = previous_threads(previous)
    panels = {p.get("idx"): p for p in script.get("panels", []) if isinstance(p, dict)}
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
        indices = item.get("evidence_panel_idxs") or []
        quote = str(item.get("evidence_quote") or "").strip()
        fact = str(item.get("new_fact") or "").strip()
        panel_text = "\n".join(str(panels[i].get(k) or "") for i in indices
                               if i in panels for k in ("narration", "key_text"))
        if not indices or any(i not in panels or panels[i].get("panel_type") in
                              {"DISCLAIMER", "TEXT_CARD"} for i in indices):
            errors.append("thread_evidence_panel_missing")
        if not quote or quote not in panel_text or not fact:
            errors.append("thread_evidence_missing")
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
        "and a new fact. Do not copy an unresolved sentence into resolved_threads.\n"
        "RESOLVED requires an independently reviewed actual answer. If no independent "
        "review is available, keep it OPEN/PROGRESSED and resolved_threads empty.\n"
        "Do not put transition objects in the legacy string arrays.\n"
        + json.dumps(threads, ensure_ascii=False)
    )
