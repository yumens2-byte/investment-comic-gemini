"""Side gates SG-0..SG-8 as pure functions (values in, GateResult out)."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from sidestory.core.canon_rules import DISCLAIMER, find_stage_violations, find_vendor_terms
from sidestory.core.models import EchoPack, GateResult, MainEpisodeRow

# Phrases that would declare a main thread resolved/advanced from the side track (EC-3).
_MAIN_THREAD_RESOLUTION = re.compile(r"(해결(되었|됐|했)|결말(이 났|났)|끝났다|resolved|paid off)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def sg0_anchor(anchor: MainEpisodeRow | None, is_publish_day: bool, force: bool) -> GateResult:
    if not is_publish_day and not force:
        return GateResult(gate="SG-0", passed=False, skip=True, reason="not a Tue/Thu slot")
    if anchor is None:
        return GateResult(gate="SG-0", passed=False, skip=True, reason="no published main anchor")
    return GateResult(gate="SG-0", passed=True, reason=anchor.main_episode_id)


def fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sg1_record(main_fingerprint: str | None) -> GateResult:
    if not main_fingerprint or not re.fullmatch(r"[0-9a-f]{32,64}", main_fingerprint):
        return GateResult(gate="SG-1", passed=False, reason="main fingerprint unavailable")
    return GateResult(gate="SG-1", passed=True, reason=main_fingerprint)


def sg7_unchanged(before: str | None, after: str | None) -> GateResult:
    if not before or not after:
        return GateResult(gate="SG-7", passed=False, reason="missing fingerprint")
    if before != after:
        return GateResult(gate="SG-7", passed=False, reason="main state changed during side run")
    return GateResult(gate="SG-7", passed=True)


def _texts(script: dict[str, Any]) -> list[str]:
    out = [str(script.get(k) or "") for k in ("title", "logline", "caption")]
    for panel in script.get("panels") or []:
        if isinstance(panel, dict):
            out += [str(panel.get(k) or "") for k in ("key_text", "narration")]
    return [t for t in out if t]


def sg3_stage(script: dict[str, Any], stage: str) -> GateResult:
    violations: list[str] = []
    for text in _texts(script):
        violations += find_stage_violations(text, stage)
    return GateResult(gate="SG-3", passed=not violations, reason="; ".join(violations))


def sg4_echo_contract(script: dict[str, Any], echo: EchoPack) -> GateResult:
    """EC-1 cite main episode, EC-2 numbers only from echo, EC-3 no main-thread resolution."""
    joined = "\n".join(_texts(script))
    problems: list[str] = []
    if echo.main_episode_id not in joined and (not echo.title or echo.title not in joined):
        problems.append("EC-1 main episode not cited")
    allowed = {_norm(v) for v in echo.market.values() if isinstance(v, int | float)}
    for token in _NUMBER.findall(joined):
        if "." in token and _norm(float(token)) not in allowed:
            problems.append(f"EC-2 number not in echo: {token}")
    for thread in echo.main_threads:
        for text in _texts(script):
            if thread[:12] in text and _MAIN_THREAD_RESOLUTION.search(text):
                problems.append("EC-3 main thread resolved in side story")
    return GateResult(gate="SG-4", passed=not problems, reason="; ".join(problems))


def _norm(value: float) -> str:
    return f"{float(value):.2f}"


def sg5_copy(final_caption: str, all_copy: Iterable[str]) -> GateResult:
    problems: list[str] = []
    if DISCLAIMER not in final_caption:
        problems.append("disclaimer missing")
    for text in all_copy:
        problems += [f"vendor term: {t}" for t in find_vendor_terms(text)]
    return GateResult(gate="SG-5", passed=not problems, reason="; ".join(sorted(set(problems))))


def sg6_manifest(expected: dict[str, str], actual: dict[str, str]) -> GateResult:
    if not expected or expected != actual:
        return GateResult(gate="SG-6", passed=False, reason="slide manifest mismatch")
    return GateResult(gate="SG-6", passed=True)
