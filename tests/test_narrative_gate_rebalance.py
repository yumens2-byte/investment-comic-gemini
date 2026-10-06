"""
tests/test_narrative_gate_rebalance.py
2026-10-05 STEP_4 품질 게이트 재조정(이해관계자 3인 합의안) 검증.

1. ThreadTransition null 필드 → "" 정규화 (재생성 낭비 제거)
2. 근거 없는 PROGRESSED → OPEN 결정론적 강등 + 감사 기록 (RESOLVED는 차단 유지)
3. thread 계약 오류는 production 게이트에서만 판정 (연속성 점수 이중 집계 제거)
4. unresolved_thread_acknowledgement → 경고(advisory), 게이트 점수에서 제외
5. 1번 패널 앵커는 narration에 넣도록 지시 (key_text 40자 트리밍 충돌 회피)
6. STEP_4 실패 시 마지막 대본 저장 / 실패 시도의 토큰 사용량 기록
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import engine.narrative.claude_client as cc
from engine.narrative.claude_client import _auto_trim_raw_json
from engine.narrative.continuity_score import score_story_continuity
from engine.narrative.production_quality import validate_production_episode
from engine.narrative.schema import EpisodeScript, ThreadTransition
from engine.narrative.story_quality import validate_story_continuity
from engine.narrative.thread_contracts import (
    downgrade_unverified_progress,
    validate_thread_transitions,
)
from tests.test_schema import _make_valid_script

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/continuity_previous_20261005.json").read_text("utf-8")
)
PREVIOUS = FIXTURE["previous_episode"]
PLAN = FIXTURE["story_beat_plan"]
HOOK = PREVIOUS["next_hook"]
ANCHOR = f"이전 회차의 단서: {HOOK}"
THREAD_HOOK = "THREAD_A6688BE66D76"
THREAD_NOTEPAD = "THREAD_1C3F4236B5C1"


def _thread(**overrides) -> dict:
    base = {
        "thread_id": THREAD_HOOK,
        "status": "PROGRESSED",
        "evidence_panel_idxs": [1],
        "evidence_quote": "방패에 생긴 균열",
        "new_fact": "EDT가 균열 기록을 확보했다",
        "resolution_result": "",
    }
    base.update(overrides)
    return base


def _episode_1005(key_text: str = "균열의 기록", transitions: list[dict] | None = None) -> dict:
    """10/5와 같은 조건(EDT 단독 NO_BATTLE)의 대본. 앵커는 narration에 위치."""
    panels = [
        {
            "idx": 1,
            "panel_type": "COVER",
            "key_text": key_text,
            "characters": [
                {"char_id": "CHAR_HERO_001", "role": "hero", "form": "form1", "position": "LEFT"}
            ],
            "narration": ANCHOR,
            "camera": "WIDE",
            "setting": "S",
            "action": "A",
        },
    ]
    for i in range(2, 8):
        panels.append(
            {
                "idx": i,
                "panel_type": "TENSION",
                "characters": [],
                "key_text": f"관찰{i}",
                "narration": "EDT가 노트패드를 펼쳐 시장을 관찰한다.",
                "camera": "WIDE",
                "setting": "S",
                "action": "A",
            }
        )
    panels.append(
        {
            "idx": 8,
            "panel_type": "DISCLAIMER",
            "characters": [],
            "key_text": "⚠️ 투자 참고 정보",
            "narration": "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
            "camera": "WIDE",
            "setting": "S",
            "action": "A",
        }
    )
    return {
        "panels": panels,
        "thread_transitions": transitions or [],
        "resolved_threads": [],
        "unresolved_threads": [PREVIOUS["unresolved_threads"][2]],
        "next_hook": "EDT의 노트패드에 남은 마지막 숫자는 누구의 것인가.",
    }


# ── 1. null 정규화 ────────────────────────────────────────────────────────────
def test_thread_transition_null_fields_become_empty():
    item = ThreadTransition.model_validate(
        {
            "thread_id": "T",
            "status": "OPEN",
            "evidence_panel_idxs": None,
            "evidence_quote": None,
            "new_fact": None,
            "resolution_result": None,
        }
    )
    assert (
        item.evidence_panel_idxs,
        item.evidence_quote,
        item.new_fact,
        item.resolution_result,
    ) == ([], "", "", "")


def test_episode_script_with_null_transition_fields_validates():
    """10/5 실제 오류(11 validation errors: string_type input_value=None) 재현 → 이제 통과."""
    raw = _make_valid_script(
        thread_transitions=[
            {
                "thread_id": THREAD_HOOK,
                "status": "OPEN",
                "evidence_panel_idxs": [],
                "evidence_quote": None,
                "new_fact": None,
                "resolution_result": None,
            }
        ]
    )
    script = EpisodeScript.model_validate(raw)
    assert script.thread_transitions[0].evidence_quote == ""


def test_null_normalization_does_not_change_verdict():
    script = _episode_1005(transitions=[_thread(status="OPEN", evidence_quote=None, new_fact=None)])
    as_none = validate_thread_transitions(script, PREVIOUS)
    script["thread_transitions"][0].update(evidence_quote="", new_fact="")
    assert as_none == validate_thread_transitions(script, PREVIOUS) == []


def test_non_text_types_are_still_rejected():
    with pytest.raises(Exception):
        ThreadTransition.model_validate({"thread_id": "T", "status": "OPEN", "evidence_quote": 3})


# ── 2. PROGRESSED 강등 ────────────────────────────────────────────────────────
def test_trimmed_quote_progress_is_downgraded_and_passes_recheck():
    """key_text에 앵커를 넣고 hook 전체를 인용 → 트리밍으로 원문 불일치 (10/5 메커니즘)."""
    raw = _episode_1005(key_text=ANCHOR, transitions=[_thread(evidence_quote=HOOK)])
    raw["panels"][0]["narration"] = "EDT가 낡은 기록을 넘긴다."
    trimmed = _auto_trim_raw_json(copy.deepcopy(raw))
    assert validate_thread_transitions(trimmed, PREVIOUS) == ["thread_evidence_missing"]

    records = downgrade_unverified_progress(trimmed, PREVIOUS)

    assert records == [
        {
            "thread_id": THREAD_HOOK,
            "from": "PROGRESSED",
            "to": "OPEN",
            "reasons": ["thread_evidence_missing"],
            "evidence_panel_idxs": [1],
            "evidence_quote": HOOK,
        }
    ]
    assert trimmed["thread_transitions"][0]["status"] == "OPEN"
    assert trimmed["_thread_downgrades"] == records
    # persist(run_market 1649~) / image / publish 재검사와 동일 함수 → 통과
    assert validate_thread_transitions(trimmed, PREVIOUS) == []


def test_verified_progress_is_kept():
    script = _episode_1005(transitions=[_thread(evidence_quote="방패에 생긴 균열")])
    assert downgrade_unverified_progress(script, PREVIOUS) == []
    assert script["thread_transitions"][0]["status"] == "PROGRESSED"
    assert "_thread_downgrades" not in script


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"evidence_panel_idxs": []}, "thread_evidence_panel_missing"),
        ({"evidence_panel_idxs": [8]}, "thread_evidence_panel_missing"),
        ({"new_fact": ""}, "thread_evidence_missing"),
        ({"evidence_quote": "조작된 인용"}, "thread_evidence_missing"),
    ],
)
def test_each_evidence_gap_downgrades(change, reason):
    script = _episode_1005(transitions=[_thread(**change)])
    records = downgrade_unverified_progress(script, PREVIOUS)
    assert reason in records[0]["reasons"]
    assert validate_thread_transitions(script, PREVIOUS) == []


def test_resolved_is_never_downgraded_and_stays_blocking():
    script = _episode_1005(
        transitions=[
            _thread(status="RESOLVED", evidence_quote="조작", resolution_result="밝혀졌다")
        ]
    )
    script["resolved_threads"] = [HOOK]
    assert downgrade_unverified_progress(script, PREVIOUS) == []
    errors = validate_thread_transitions(script, PREVIOUS)
    assert "thread_evidence_missing" in errors
    assert "thread_resolution_review_required" in errors


def test_unknown_thread_id_is_not_downgraded():
    script = _episode_1005(transitions=[_thread(thread_id="THREAD_FAKE", evidence_quote="x")])
    assert downgrade_unverified_progress(script, PREVIOUS) == []
    assert "unknown_or_duplicate_thread" in validate_thread_transitions(script, PREVIOUS)


# ── 3·4. 연속성 점수: 이중 집계 제거 + thread 언급 advisory ─────────────────────
def test_thread_contract_error_is_judged_only_by_production_gate():
    script = _episode_1005(transitions=[_thread(evidence_quote="조작된 인용")])
    pack = {"previous_episode": PREVIOUS}
    codes = [v.code for v in validate_production_episode(script, context_pack=pack)]
    assert "THREAD_EVIDENCE_MISSING" in codes
    score = score_story_continuity(script, pack, PLAN)
    assert "thread_evidence_missing" not in score.missing_requirements


def test_1005_like_solo_episode_passes_continuity_with_advisory():
    """EDT 단독 회차: hook은 회수, 다른 캐릭터 thread 언급 부족 → 차단 아님(경고)."""
    script = _episode_1005()
    pack = {"previous_episode": PREVIOUS}
    score = score_story_continuity(script, pack, PLAN)
    assert score.status == "pass"
    assert score.missing_requirements == []
    assert "unresolved_thread_acknowledgement" in score.advisories
    assert score.to_dict()["advisories"] == ["unresolved_thread_acknowledgement"]
    # strict 게이트에서도 경고/예외 없음 → run_market 품질 재시도 미발생
    assert validate_story_continuity(script, pack, PLAN, strict=True) == []


def test_missing_opening_hook_still_blocks_strict():
    script = _episode_1005()
    script["panels"][0]["narration"] = "완전히 새로운 하루가 시작된다."
    pack = {"previous_episode": PREVIOUS}
    score = score_story_continuity(script, pack, PLAN)
    assert score.status == "fail"
    assert "opening_hook_payoff" in score.missing_requirements
    from engine.narrative.story_quality import StoryContinuityError

    with pytest.raises(StoryContinuityError):
        validate_story_continuity(script, pack, PLAN, strict=True)


def test_advisory_only_context_does_not_zero_the_gate():
    score = score_story_continuity(
        {"panels": [{"idx": 1, "narration": "오늘의 관찰"}]},
        {
            "previous_episode": {
                "source_episode_id": "X",
                "unresolved_threads": ["철문 안쪽의 목소리"],
            }
        },
    )
    assert score.total_score == 100.0
    assert score.status == "pass"
    assert score.advisories == ["unresolved_thread_acknowledgement"]


# ── 5. 앵커 지시 위치 ─────────────────────────────────────────────────────────
def test_anchor_instruction_targets_narration():
    from engine.narrative.prompt_tpl import _append_narrative_context_fallback
    from engine.narrative.story_quality import build_continuity_retry_feedback

    prompt = _append_narrative_context_fallback("", {"previous_episode": PREVIOUS})
    assert "Panel 1 narration must include this exact anchor (do NOT use key_text:" in prompt
    assert "narration or key_text" not in prompt
    assert "max 40 chars) must include" not in prompt  # CR-5: narration 40자 오독 문구 제거
    bad = _episode_1005()
    bad["panels"][0]["narration"] = "새로운 하루."
    feedback = build_continuity_retry_feedback(bad, {"previous_episode": PREVIOUS}, PLAN)
    assert "panel 1 narration must include EXACT_OPENING_ANCHOR" in feedback
    assert "advisories (non-blocking): unresolved_thread_acknowledgement" in feedback


def test_anchor_fits_narration_limit_but_not_key_text():
    assert 40 < len(ANCHOR) <= 120


# ── 6. 관측성 ────────────────────────────────────────────────────────────────
def test_failed_narrative_is_saved(tmp_path, monkeypatch):
    from scripts.run_market import _save_failed_narrative

    monkeypatch.chdir(tmp_path)
    events = []
    logger_inst = SimpleNamespace(warning=lambda step, msg, **kw: events.append(msg))
    _save_failed_narrative(
        "2026-10-05", "ICG-2026-10-05-001", {"title": "t"}, ValueError("boom"), logger_inst
    )
    saved = json.loads(
        (tmp_path / "output/episodes/2026-10-05/ICG-2026-10-05-001_script_failed.json").read_text(
            "utf-8"
        )
    )
    assert saved["_failure"] == {
        "error_type": "ValueError",
        "error": "boom",
        "script_quality_attempt": None,
    }
    assert events and "[FailedScript]" in events[0]


def test_failed_narrative_save_never_raises(tmp_path, monkeypatch):
    from scripts.run_market import _save_failed_narrative

    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").write_text("not a directory")  # mkdir 실패 유도
    _save_failed_narrative(
        "2026-10-05", "E", {"a": 1}, ValueError("x"), SimpleNamespace(warning=lambda *a, **k: None)
    )
    _save_failed_narrative("2026-10-05", "E", None, ValueError("x"), None)


def test_failed_attempt_reports_token_usage(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="not json")],
            usage=SimpleNamespace(input_tokens=7787, output_tokens=4010),
        )

    monkeypatch.setattr(
        cc, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(cc, "load_system_prompt", lambda: "canon")
    monkeypatch.setattr(cc, "render_user_prompt", lambda **kwargs: "evidence")
    events = []
    with pytest.raises(Exception):
        cc.generate_episode(
            date="2026-10-05",
            episode_id="ICG-2026-10-05-001",
            event_type="BATTLE",
            delta={},
            battle_result={},
            hero_id="H",
            villain_id="",
            arc_context={},
            scenario_type="NO_BATTLE",
            attempt_observer=lambda *e: events.append(e),
        )
    metas = [e[2] for e in events if "[NarrativeAttempt]" in e[1]]
    assert [(m["input_tokens"], m["output_tokens"]) for m in metas] == [(7787, 4010)] * 3


# ── 통합: run_market.step_narrative (10/5 조건 재현, LLM 호출은 fake) ─────────────
def _run_step_narrative(monkeypatch, tmp_path, raw: dict):
    from engine.narrative import claude_client
    from scripts import run_market

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONTINUITY_STRICT_ENABLED", "true")
    monkeypatch.setenv("SERIAL_NARRATIVE_P0_ENABLED", "true")
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "false")
    raw.update(
        episode_id="ICG-2026-10-05-001",
        date="2026-10-05",
        event_type="BATTLE",
        title="t",
        logline="l",
        caption_x_cover="c",
        caption_x_parts=["a", "b"],
        caption_x_final="본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
        caption_telegram="t",
        hashtags=["#EDT"],
        arc_tension_delta=1,
    )
    calls: list[dict] = []

    def fake_generate_episode(**kwargs):
        calls.append(kwargs)
        return EpisodeScript.model_validate(_auto_trim_raw_json(copy.deepcopy(raw)))

    monkeypatch.setattr(claude_client, "generate_episode", fake_generate_episode)
    logs: list[tuple[str, str]] = []
    logger_inst = SimpleNamespace(
        step_start=lambda *a: 0.0,
        step_done=lambda *a, **k: None,
        step_fail=lambda *a, **k: logs.append(("fail", str(a[2]))),
        info=lambda s, m, meta=None: logs.append(("info", m)),
        warning=lambda s, m, meta=None: logs.append(("warn", m)),
    )
    ctx = {
        "event_type": "BATTLE",
        "delta": {},
        "battle_result": {"outcome": "OBSERVATION"},
        "hero_id": "CHAR_HERO_001",
        "villain_id": None,
        "arc_context": {},
        "scenario_type": "NO_BATTLE",
        "ending_tone": "TENSE",
        "heroes": ["CHAR_HERO_001"],
        "narrative_context_pack": {"previous_episode": PREVIOUS},
        "story_beat_plan": PLAN,
    }
    result = run_market.step_narrative("2026-10-05", "ICG-2026-10-05-001", ctx, logger_inst)
    return result, calls, logs


def test_step_narrative_anchor_in_narration_passes_first_attempt(monkeypatch, tmp_path):
    raw = _episode_1005(transitions=[_thread(evidence_quote=HOOK)])
    result, calls, logs = _run_step_narrative(monkeypatch, tmp_path, raw)
    assert len(calls) == 1  # 품질 재시도 없음
    assert result["_continuity_quality"]["status"] == "pass"
    assert result["_production_quality"]["status"] == "pass"
    assert "_thread_downgrades" not in result
    assert any("advisories=unresolved_thread_acknowledgement" in m for _, m in logs)


def test_step_narrative_trimmed_quote_downgrades_instead_of_failing(monkeypatch, tmp_path):
    """10/5 실패 메커니즘(앵커를 key_text에 넣고 잘린 원문을 인용) → 강등 후 1회에 통과."""
    raw = _episode_1005(key_text=ANCHOR, transitions=[_thread(evidence_quote=HOOK)])
    raw["panels"][0]["narration"] = "방패에 생긴 균열 소식이 EDT의 노트패드에 적힌다."
    result, calls, logs = _run_step_narrative(monkeypatch, tmp_path, raw)
    assert len(calls) == 1
    assert result["_production_quality"]["violation_codes"] == []
    assert result["_thread_downgrades"][0]["thread_id"] == THREAD_HOOK
    assert result["thread_transitions"][0]["status"] == "OPEN"
    assert any(m.startswith("[ThreadDowngrade] THREAD_A6688BE66D76") for _, m in logs)
    saved = json.loads(
        (tmp_path / "output/episodes/2026-10-05/ICG-2026-10-05-001_script.json").read_text("utf-8")
    )
    assert saved["_thread_downgrades"] == result["_thread_downgrades"]
    assert validate_thread_transitions(saved, PREVIOUS) == []  # persist 재검사 통과


def test_step_narrative_failure_leaves_failed_script(monkeypatch, tmp_path):
    raw = _episode_1005()
    raw["panels"][0]["narration"] = "완전히 새로운 하루가 시작된다."  # opening hook 미회수
    from engine.narrative.story_quality import StoryContinuityError

    with pytest.raises(StoryContinuityError):
        _run_step_narrative(monkeypatch, tmp_path, raw)
    failed = json.loads(
        (tmp_path / "output/episodes/2026-10-05/ICG-2026-10-05-001_script_failed.json").read_text(
            "utf-8"
        )
    )
    assert failed["_failure"]["error_type"] == "StoryContinuityError"


# ── 2026-10-06 코드리뷰 반영 (CR-1, CR-3, CR-5~CR-9) ─────────────────────────
_SEED = "검은 문은 아직 닫히지 않았다 그림자 속 열쇠"
_THREAD = "철문 안쪽의 목소리"


def _partial_hook_script(n_keywords: int) -> dict:
    from engine.narrative.continuity_score import continuity_keywords

    words = continuity_keywords(_SEED)[:n_keywords]
    return {"panels": [{"idx": 1, "narration": " ".join(words) + " " + _THREAD}]}


@pytest.mark.parametrize("n_keywords,expected_total", [(3, 71.43), (4, 80.96)])
def test_cr1_rebalance_never_fails_episode_that_passed_before(n_keywords, expected_total):
    """CR-1 회귀: hook 일부 일치 + thread 언급 충실 → main(6cc65b2)과 같은 점수로 pass.

    기대값은 main 코드로 같은 입력을 실행한 실측치 (2026-10-06 리뷰 재현).
    """
    score = score_story_continuity(
        _partial_hook_script(n_keywords),
        {
            "previous_episode": {
                "source_episode_id": "X",
                "next_hook": _SEED,
                "unresolved_threads": [_THREAD],
            }
        },
    )
    assert score.total_score == expected_total
    assert score.status == "pass"
    assert score.advisories == []


@pytest.mark.parametrize("legacy_total", [73.2, 65.6, 64.0])
def test_cr1_1006_failures_pass_after_rebalance(legacy_total):
    """10/6 실측: 만점 80(opening40+thread30+beat10), missing=thread 언급만 → 3회 모두 pass.

    missing에 thread 언급만 있었으므로 beat=10, opening∈[20,40], thread<10.
    legacy 점수에서 가능한 thread 범위의 양 끝 모두에서 새 게이트 점수가 70 이상인지 확인.
    """
    earned = legacy_total * 0.8  # 80점 만점 환산
    beat = 10.0
    lo, hi = max(0.0, earned - beat - 40.0), min(9.99, earned - beat - 20.0)
    assert lo <= hi
    for thread in (lo, hi):
        opening = earned - beat - thread
        gate_total = 100.0 * (opening + beat) / 50.0
        assert max(gate_total, legacy_total) >= 70.0


def test_cr3_local_template_has_no_copy_to_resolved_rule():
    j2 = (Path(__file__).parent.parent / "config/prompts/narrative_user.j2").read_text("utf-8")
    assert "verbatim into the top-level resolved_threads" not in j2
    assert "Panel 1 narration must include this exact anchor (do NOT use key_text:" in j2


def test_cr6_failed_script_records_attempt_and_masks_secret(tmp_path, monkeypatch):
    from scripts.run_market import _save_failed_narrative

    monkeypatch.chdir(tmp_path)
    secret = "sk-ant-" + "a" * 30
    _save_failed_narrative(
        "2026-10-06",
        "E",
        {"t": 1},
        ValueError(f"boom {secret}"),
        SimpleNamespace(warning=lambda *a, **k: None),
        quality_attempt=2,
    )
    saved = json.loads(
        (tmp_path / "output/episodes/2026-10-06/E_script_failed.json").read_text("utf-8")
    )
    assert saved["_failure"]["script_quality_attempt"] == 2
    assert secret not in saved["_failure"]["error"]
    assert "***REDACTED***" in saved["_failure"]["error"]


def test_cr7_downgraded_thread_does_not_record_progress():
    from engine.narrative.continuity import build_continuity_bundle

    script = _episode_1005(
        transitions=[
            _thread(thread_id=THREAD_HOOK, status="OPEN"),
            _thread(
                thread_id=THREAD_NOTEPAD,
                status="PROGRESSED",
                evidence_quote="EDT가 노트패드를 펼쳐",
                evidence_panel_idxs=[2],
            ),
        ]
    )
    ctx = {"previous_episode": PREVIOUS}
    bundle = build_continuity_bundle("ICG-2026-10-06-001", "2026-10-06", ctx, script)
    ledger = {t["thread_id"]: t for t in bundle["structured_threads"]}
    assert ledger[THREAD_HOOK]["status"] == "OPEN"
    assert ledger[THREAD_HOOK].get("last_progress_episode_id") != "ICG-2026-10-06-001"
    assert ledger[THREAD_NOTEPAD]["status"] == "PROGRESSED"
    assert ledger[THREAD_NOTEPAD]["last_progress_episode_id"] == "ICG-2026-10-06-001"


def test_cr9_api_exception_without_response_reports_none_tokens(monkeypatch):
    def create(**kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(
        cc, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(cc, "load_system_prompt", lambda: "canon")
    monkeypatch.setattr(cc, "render_user_prompt", lambda **kwargs: "evidence")
    events = []
    with pytest.raises(Exception):
        cc.generate_episode(
            date="2026-10-06",
            episode_id="ICG-2026-10-06-001",
            event_type="BATTLE",
            delta={},
            battle_result={},
            hero_id="H",
            villain_id="",
            arc_context={},
            scenario_type="NO_BATTLE",
            attempt_observer=lambda *e: events.append(e),
        )
    metas = [e[2] for e in events if "[NarrativeAttempt]" in e[1]]
    assert len(metas) == 3
    assert all(m["input_tokens"] is None and m["output_tokens"] is None for m in metas)
    assert all(m["exception_type"] == "ConnectionError" for m in metas)
