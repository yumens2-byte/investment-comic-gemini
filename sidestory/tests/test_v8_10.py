"""v8.10: trim keep-ratio/aspect guard (pilot 2 P5) and internal outcome codes (pilot 2 P2)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from PIL import Image

from sidestory.app.imaging import MAX_KEPT_ASPECT, MIN_KEEP_RATIO, TrimResult, detect_bands
from sidestory.app.p1 import P1Deps, render_user_prompt, run_p1, run_stage
from sidestory.core.models import OutcomeClass
from sidestory.core.outcome import (
    CLASS_LABEL_KO,
    INTERNAL_CODES,
    MAIN_OUTCOMES,
    OUTCOME_LABEL_KO,
    outcome_label_ko,
)
from sidestory.core.script import find_internal_codes, normalize, validate
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row
from sidestory.tests.p1_fixtures import (
    FakeComposer,
    FakeImages,
    FakeInspector,
    FakeLLM,
    FakePrompts,
    echo_for,
    make_refs,
    raw_script,
)

TUE = date(2026, 10, 6)
SID = "SIDE-2026-10-06-01"


def _pilot2_p5() -> np.ndarray:
    """1024² white canvas, wide scene in rows 206..806 framed by a 3 px black rule."""
    rng = np.random.default_rng(7)
    a = np.full((1024, 1024, 3), 250, dtype=np.uint8)
    a[200:812] = rng.integers(40, 200, (612, 1024, 3), dtype=np.uint8)
    a[200:203], a[809:812] = 0, 0
    return a


# ── 10-1 ─────────────────────────────────────────────────────────────────────
def test_thresholds() -> None:
    assert MIN_KEEP_RATIO == 0.50 and MAX_KEPT_ASPECT == 2.0


def test_aspect_property() -> None:
    assert TrimResult((0, 0, 100, 100), (100, 100), 1.0).aspect == 1.0
    assert TrimResult((0, 206, 1024, 806), (1024, 1024), 0.586).aspect == pytest.approx(1024 / 600)
    assert TrimResult((10, 0, 60, 300), (100, 300), 0.1).aspect == 6.0


def test_pilot2_p5_shape_is_detected_below_old_threshold() -> None:
    res = detect_bands(Image.fromarray(_pilot2_p5()))
    assert 0.50 <= res.kept_ratio < 0.60 and res.aspect < 2.0
    assert res.box[1] >= 203 and res.box[3] <= 809


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return P1Deps(
        feed=FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,)),
        store=FakeStore(), llm=FakeLLM([raw_script()]), prompts=FakePrompts(),
        images=FakeImages(), composer=FakeComposer(), characters=make_refs(tmp_path),
        output_root=tmp_path / "output/sidestory", ref_root=tmp_path, inspector=FakeInspector())


def test_pilot2_p5_assembles_now(env) -> None:
    class P5Letterbox(FakeImages):
        def generate(self, panel_idx, prompt, refs, output_dir, aspect_ratio=None):
            path, cost = super().generate(panel_idx, prompt, refs, output_dir, aspect_ratio)
            if panel_idx == 5:
                Image.fromarray(_pilot2_p5()).save(path)
            return path, cost

    env.images = P5Letterbox()
    res = run_p1(TUE, env)
    assert res[-1].status == "assembled"
    assert "P5" in env.store.get_episode(SID)["manifest_json"]["trimmed"]


@pytest.mark.parametrize("box,size,kept,needle", [
    ((0, 0, 70, 70), (100, 100), 0.49, "keep only 49%"),
    ((0, 300, 1024, 700), (1024, 1024), 0.70, "strip"),     # 2.56:1, area check alone passes
])
def test_assembly_guards_hold(env, monkeypatch, box, size, kept, needle) -> None:
    from sidestory.app import p1 as mod

    run_p1(TUE, env)
    monkeypatch.setattr(mod, "trim_panel", lambda src, d: (src, TrimResult(box, size, kept)))
    res = run_stage("assembly", TUE, env)
    assert res.status == "hold" and needle in res.detail["reason"]


def test_assembly_accepts_exact_limits(env, monkeypatch) -> None:
    from sidestory.app import p1 as mod

    run_p1(TUE, env)
    monkeypatch.setattr(mod, "trim_panel", lambda src, d: (src, TrimResult(
        (0, 256, 1024, 768), (1024, 1024), 0.50)))          # exactly 50% and 2:1
    assert run_stage("assembly", TUE, env).status == "assembled"


# ── 10-2 ─────────────────────────────────────────────────────────────────────
def test_every_code_has_a_korean_label() -> None:
    assert set(OUTCOME_LABEL_KO) == MAIN_OUTCOMES
    assert set(CLASS_LABEL_KO) == set(OutcomeClass)
    for label in [*OUTCOME_LABEL_KO.values(), *CLASS_LABEL_KO.values()]:
        assert not find_internal_codes(label)
    assert outcome_label_ko(" observation ") == "관측(전투 없음)"
    assert outcome_label_ko(None) is None and outcome_label_ko("UNKNOWN") is None


@pytest.mark.parametrize("text,codes", [
    ("본편의 결과는 OBSERVATION.", ["OBSERVATION"]),
    ("본편은 DRAW로 끝났다", ["DRAW"]),
    ("HERO_TACTICAL_VICTORY 이후", ["HERO_TACTICAL_VICTORY"]),
    ("NO_BATTLE/VICTORY", ["NO_BATTLE", "VICTORY"]),
    ("they draw a line; Victory lap", []),            # ordinary words, not codes
    ("DRAWN SYSTEM_COLLAPSED", []),                   # longer tokens are not codes
    ("REDRAW PRE_OBSERVATION", []),
    ("본편은 무승부로 끝났다", []),
])
def test_find_internal_codes(text, codes) -> None:
    assert find_internal_codes(text) == codes


@pytest.mark.parametrize("field", ["narration", "key_text", "caption_fb", "title", "logline",
                                   "next_hook_side"])
def test_validation_rejects_codes_in_reader_text(field) -> None:
    echo = echo_for()
    raw = raw_script()
    if field in {"narration", "key_text"}:
        raw["panels"][1][field] = raw["panels"][1][field][:20] + " OBSERVATION"
    else:
        raw[field] = raw[field][:30] + " OBSERVATION"
    _, problems = validate(normalize(raw, side_episode_id=SID, echo=echo), echo, "E01")
    assert any("internal codes ['OBSERVATION']" in p for p in problems), problems


def test_clean_script_still_passes() -> None:
    echo = echo_for()
    _, problems = validate(normalize(raw_script(), side_episode_id=SID, echo=echo), echo, "E01")
    assert problems == []


@pytest.mark.parametrize("outcome,scenario,cls_ko,out_ko", [
    ("HERO_VICTORY", "ONE_VS_ONE", "승리", "히어로 승리"),
    ("DRAW", "ONE_VS_ONE", "무승부", "무승부"),
    ("OBSERVATION", "NO_BATTLE", "전투 없음", "관측(전투 없음)"),
])
def test_prompt_shows_korean_names_only(outcome, scenario, cls_ko, out_ko) -> None:
    echo = echo_for(outcome, scenario)
    text = render_user_prompt(side_episode_id_=SID, echo=echo, nn_stage="E01",
                              previous_hook=None, feedback=[])
    assert f"결과 분류: {cls_ko} (본편 결과: {out_ko})" in text
    assert f"## 반응 비트 ({cls_ko})" in text
    body = text.split("## 규칙")[0]
    assert not find_internal_codes(body), find_internal_codes(body)
    assert all(code in INTERNAL_CODES for code in ("DRAW", "NO_BATTLE", "ONE_VS_ONE"))


def test_scenario_labels() -> None:
    from sidestory.core.outcome import scenario_label_ko

    assert scenario_label_ko("no_battle") == "전투 없음" and scenario_label_ko(None) is None
    assert scenario_label_ko("ALLIANCE") == "연합 대결"
    assert scenario_label_ko("NEW_KIND") == "NEW_KIND"    # unknown: shown as-is, not guessed


def test_scenario_vocabulary_drift() -> None:
    """Fails when main adds a scenario type, so its Korean label is added together."""
    from typing import get_args

    from engine.narrative.scenario_selector import ScenarioType
    from sidestory.core.outcome import SCENARIO_LABEL_KO

    assert set(get_args(ScenarioType)) == set(SCENARIO_LABEL_KO)
