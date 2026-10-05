"""P1 stages: narrative → image → assembly (+ p1 = all remaining). No publishing here.

Every stage: load row → transition check → SG-1 main fingerprint → work → gates →
compare-and-set status → SG-7. Any failure moves the episode to ``hold`` with the reason.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image

from sidestory.app.imaging import MIN_KEEP_RATIO, trim_panel
from sidestory.app.pipeline import run_gate_and_echo, side_episode_id
from sidestory.app.settings import CONFIG_DIR
from sidestory.core import gates, lifecycle
from sidestory.core.beats import beats_for
from sidestory.core.canon_rules import DISCLAIMER, REACTION_BEATS
from sidestory.core.image_prompt import build_panel_spec, registered_refs
from sidestory.core.models import EchoPack, GateResult
from sidestory.core.schedule import previous_slot
from sidestory.core.script import SideScript, normalize, validate
from sidestory.ports.image import ImageGenerator, ImageHold, SlideComposer
from sidestory.ports.llm import LLMError, NarrativeLLM, PromptSource
from sidestory.ports.main_feed import MainFeedReader
from sidestory.ports.market_source import DxySource
from sidestory.ports.store import SideStore

MAX_NARRATIVE_ATTEMPTS = 3          # 1 + 2 regenerations (P1 §2-4)
MAX_FEEDBACK_ITEMS = 15
IMAGE_PANELS = range(1, 7)          # 7 data card / 8 disclaimer are PIL text slides
SLIDE_SIZE = (1080, 1350)


@dataclass
class P1Deps:
    feed: MainFeedReader
    store: SideStore
    llm: NarrativeLLM | None = None
    prompts: PromptSource | None = None
    images: ImageGenerator | None = None
    composer: SlideComposer | None = None
    characters: dict[str, Any] = field(default_factory=dict)
    nn_stage: str = "E01"
    output_root: Path = Path("output/sidestory")
    ref_root: Path = Path(".")
    dxy_source: DxySource | None = None


@dataclass
class StageResult:
    stage: str
    side_episode_id: str
    status: str                       # resulting episode status, or "skipped"
    gates: list[GateResult] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status not in {"hold", "error"}

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "side_episode_id": self.side_episode_id,
                "status": self.status, "gates": [g.model_dump() for g in self.gates],
                "detail": self.detail}


class StageFailure(RuntimeError):
    def __init__(self, reason: str, gates_: list[GateResult] | None = None,
                 detail: dict[str, Any] | None = None):
        super().__init__(reason)
        self.gates = gates_ or []
        self.detail = detail or {}


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def accumulate_feedback(attempts: list[list[str]]) -> list[str]:
    """Unique problems across all attempts, latest attempt first, capped."""
    out: list[str] = []
    for problems in reversed(attempts):
        for item in problems:
            if item not in out:
                out.append(item)
    return out[:MAX_FEEDBACK_ITEMS]


def render_user_prompt(*, side_episode_id_: str, echo: EchoPack, nn_stage: str,
                       previous_hook: str | None, feedback: list[str]) -> str:
    env = Environment(loader=FileSystemLoader(str(CONFIG_DIR / "prompts")),
                      undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    return env.get_template("user_side.j2").render(
        side_episode_id=side_episode_id_, echo=echo, nn_stage=nn_stage,
        previous_hook=previous_hook, reaction=REACTION_BEATS[echo.outcome_class],
        beats=beats_for(echo.outcome_class), disclaimer=DISCLAIMER, feedback=feedback)


# ── stages ──────────────────────────────────────────────────────────────────
def _narrative(sid: str, side_day: date, row: dict[str, Any], deps: P1Deps,
               echo: EchoPack) -> tuple[dict[str, Any], dict[str, Any]]:
    if deps.llm is None or deps.prompts is None:
        raise StageFailure("narrative adapters not configured")
    try:
        system = deps.prompts.system_prompt()
    except LLMError as exc:
        raise StageFailure(f"system prompt unavailable: {exc}") from exc
    prev = deps.store.get_episode(side_episode_id(previous_slot(side_day)))
    previous_hook = ((prev or {}).get("script_json") or {}).get("next_hook_side") or None
    feedback: list[str] = []
    attempts: list[list[str]] = []
    for _ in range(MAX_NARRATIVE_ATTEMPTS):
        user = render_user_prompt(side_episode_id_=sid, echo=echo, nn_stage=deps.nn_stage,
                                  previous_hook=previous_hook, feedback=feedback)
        try:
            raw = deps.llm.generate_script(system, user)
        except LLMError as exc:
            problems = [f"output error: {exc}. Return exactly one JSON object."]
        else:
            script = normalize(raw, side_episode_id=sid, echo=echo)
            _, problems = validate(script, echo, deps.nn_stage)
            if not problems:
                return {"script_json": script}, {"attempts": len(attempts) + 1}
        attempts.append(problems)
        # The model rewrites the whole script each time, so it must see every earlier
        # rejection (pilot 1 retry: fixing one problem reintroduced another).
        feedback = accumulate_feedback(attempts)
    raise StageFailure("narrative rejected after "
                       f"{MAX_NARRATIVE_ATTEMPTS} attempts: {'; '.join(attempts[-1])}",
                       detail={"attempt_problems": attempts})


def _image(sid: str, side_day: date, row: dict[str, Any], deps: P1Deps,
           echo: EchoPack) -> tuple[dict[str, Any], dict[str, Any]]:
    if deps.images is None:
        raise StageFailure("image adapter not configured")
    script = SideScript.model_validate(row["script_json"])
    story = [p for p in script.panels if p.idx in IMAGE_PANELS]
    poses = {p.zero_block_pose for p in story}
    checks = [(pose, registered, sha256_file(deps.ref_root / path) if path else None)
              for pose, path, registered in registered_refs(deps.characters, poses)]
    sg2 = gates.sg2_refs(checks)
    if not sg2.passed:
        raise StageFailure(sg2.reason, [sg2])
    out_dir = deps.output_root / side_day.isoformat() / "panels"
    panels: list[dict[str, Any]] = []
    total = 0.0
    for panel in story:
        spec = build_panel_spec(panel, deps.characters)
        refs = [deps.ref_root / spec.ref_path] if spec.ref_path else []
        try:
            path, cost = deps.images.generate(panel.idx, spec.prompt, refs, out_dir)
        except ImageHold as exc:
            raise StageFailure(f"P{panel.idx} image hold: {exc}", [sg2],
                               {"panels_done": panels, "cost_usd": round(total, 4)}) from exc
        digest = sha256_file(path)
        if digest is None:
            raise StageFailure(f"P{panel.idx} image file missing after generation", [sg2])
        total += cost
        panels.append({"idx": panel.idx, "path": _rel(path), "sha256": digest,
                       "pose": spec.pose, "ref": spec.ref_path, "cost_usd": round(cost, 4)})
    return ({"panels_json": {"panels": panels, "cost_usd": round(total, 4)}},
            {"gates": [sg2], "cost_usd": round(total, 4)})


def _assembly(sid: str, side_day: date, row: dict[str, Any], deps: P1Deps,
              echo: EchoPack) -> tuple[dict[str, Any], dict[str, Any]]:
    if deps.composer is None:
        raise StageFailure("composer not configured")
    script = SideScript.model_validate(row["script_json"])
    stored = {p["idx"]: p for p in (row.get("panels_json") or {}).get("panels", [])}
    images: list[Path | None] = []
    for panel in script.panels:
        if panel.idx not in IMAGE_PANELS:
            images.append(None)
            continue
        entry = stored.get(panel.idx)
        path = Path(entry["path"]) if entry else None
        if path is None or sha256_file(path) != entry.get("sha256"):
            raise StageFailure(f"P{panel.idx} panel artifact missing or changed — restore the "
                               "image-stage artifact (Resume only: previous run id or run URL) "
                               "before assembly")
        images.append(path)
    # B1: cut letterbox / frame bands from a copy (the paid original keeps its ledger hash).
    trim_dir = deps.output_root / side_day.isoformat() / "panels_trimmed"
    trims: dict[str, list[int]] = {}
    for i, path in enumerate(images):
        if path is None:
            continue
        used, res = trim_panel(path, trim_dir)
        if res.kept_ratio < MIN_KEEP_RATIO:
            raise StageFailure(f"{path.name} band trim would keep only {res.kept_ratio:.0%} "
                               "(misdetection) — review the panel")
        if res.trimmed:
            trims[path.stem] = list(res.box)
        images[i] = used
    out_dir = deps.output_root / side_day.isoformat() / "slides"
    try:
        slides = deps.composer.compose(
            [p.model_dump() for p in script.panels], images, out_dir)
    except ValueError as exc:
        raise StageFailure(f"composer rejected sources: {exc}") from exc
    if len(slides) != len(script.panels):
        raise StageFailure(f"expected {len(script.panels)} slides, got {len(slides)}")
    expected: dict[str, str] = {}
    for slide in slides:
        digest = sha256_file(Path(slide))
        if digest is None:
            raise StageFailure(f"slide missing: {slide}")
        with Image.open(slide) as img:
            if img.size != SLIDE_SIZE:
                raise StageFailure(f"slide {Path(slide).name} size {img.size} != {SLIDE_SIZE}")
        expected[Path(slide).name] = digest
    actual = {Path(s).name: sha256_file(Path(s)) or "" for s in slides}
    sg6 = gates.sg6_manifest(expected, actual)
    if not sg6.passed:
        raise StageFailure(sg6.reason, [sg6])
    manifest = {"slides": expected, "script_sha256": gates.fingerprint(row["script_json"]),
                "panels": {str(k): v["sha256"] for k, v in stored.items()},
                "trimmed": trims}
    slides_json = [{"name": Path(s).name, "path": _rel(Path(s)), "sha256": expected[Path(s).name]}
                   for s in slides]
    return {"slides_json": slides_json, "manifest_json": manifest}, {"gates": [sg6]}


_STAGES = {"narrative": _narrative, "image": _image, "assembly": _assembly}


def run_stage(stage: str, side_day: date, deps: P1Deps) -> StageResult:
    sid = side_episode_id(side_day)
    row = deps.store.get_episode(sid)
    if not row:
        return StageResult(stage, sid, "error", detail={"reason": "slot not echoed yet"})
    current = row.get("status", "")
    try:
        lifecycle.check_transition(stage, current)
    except lifecycle.TransitionError as exc:
        return StageResult(stage, sid, "error", detail={"reason": str(exc)})
    echo = EchoPack.model_validate(row["echo_pack_json"])
    main_day = echo.main_date
    before = deps.feed.main_fingerprint(main_day)
    sg1 = gates.sg1_record(before)
    result = StageResult(stage, sid, current, gates=[sg1])
    try:
        if not sg1.passed:
            raise StageFailure(sg1.reason)
        fields, detail = _STAGES[stage](sid, side_day, row, deps, echo)
        result.gates += detail.pop("gates", [])
        result.detail.update(detail)
        sg7 = gates.sg7_unchanged(before, deps.feed.main_fingerprint(main_day))
        result.gates.append(sg7)
        if not sg7.passed:
            raise StageFailure(sg7.reason)
        target = lifecycle.target_status(stage)
        if not deps.store.update_episode(sid, {**fields, "status": target,
                                               "error_message": None}, expect_status=current):
            result.status = "error"
            result.detail["reason"] = "status changed concurrently (compare-and-set failed)"
            deps.store.log(stage, "error", {"sid": sid, **result.detail})
            return result
        result.status = target
        deps.store.log(stage, "ok", {"sid": sid, **_loggable(result.detail)})
    except StageFailure as exc:
        result.gates += exc.gates
        result.detail.update({"reason": str(exc), **exc.detail})
        deps.store.update_episode(sid, {"status": "hold", "error_message": f"{stage}: {exc}"[:2000]},
                                  expect_status=current)
        result.status = "hold"
        deps.store.log(stage, "hold", {"sid": sid, **_loggable(result.detail)})
    return result


def _loggable(detail: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in detail.items() if k != "gates"}


def run_p1(side_day: date, deps: P1Deps, *, force: bool = False,
           retry_hold: bool = False) -> list[StageResult]:
    """echo (if the slot is new) → remaining P1 stages; stops at the first non-ok stage."""
    sid = side_episode_id(side_day)
    results: list[StageResult] = []
    row = deps.store.get_episode(sid)
    if not row:
        echo_run = run_gate_and_echo(side_day, deps.feed, deps.store, force=force,
                                     persist=True, dxy_source=deps.dxy_source)
        status = "draft" if echo_run.persisted and all(g.passed for g in echo_run.gates) else (
            "skipped" if echo_run.skipped else "error")
        results.append(StageResult("echo", sid, status, gates=echo_run.gates))
        if status != "draft":
            return results
        row = deps.store.get_episode(sid) or {}
    status = row.get("status", "")
    if status == "hold":
        if not retry_hold:
            results.append(StageResult("p1", sid, "hold", detail={
                "reason": f"episode on hold: {row.get('error_message')} (use --retry-hold)"}))
            return results
        status = lifecycle.resume_status(row)
        if not deps.store.update_episode(sid, {"status": status, "error_message": None},
                                         expect_status="hold"):
            results.append(StageResult("p1", sid, "error",
                                       detail={"reason": "hold release lost a race"}))
            return results
        deps.store.log("p1", "resume", {"sid": sid, "status": status})
    try:
        stages = lifecycle.remaining_stages(status)
    except lifecycle.TransitionError as exc:
        results.append(StageResult("p1", sid, "error", detail={"reason": str(exc)}))
        return results
    for stage in stages:
        res = run_stage(stage, side_day, deps)
        results.append(res)
        if not res.ok:
            break
    return results
