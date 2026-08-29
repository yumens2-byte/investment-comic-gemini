"""tests/test_shorts_pipeline.py — Daily Battle Shorts 게이트/각색 단위 테스트 (DB·API 미사용)."""

from __future__ import annotations

import pytest

from engine.video import shorts_pipeline as sp
from engine.video.shorts_pipeline import (
    ConsistencyGuardError,
    GateResult,
    ShortsScenario,
    build_shorts_episode_id,
    enforce_consistency,
    extract_immutable_facts,
    generate_shorts_scenario,
    run_gate,
)

DATE = "2026-08-29"


# ── episode_id 채번 규칙 (run_video_trailer._get_episode_id 와 동일) ──


def test_episode_id_format():
    assert build_shorts_episode_id(DATE) == f"icg-v-{DATE}-001"


def test_episode_id_matches_run_video_trailer_rule():
    from scripts.run_video_trailer import _get_episode_id

    assert build_shorts_episode_id(DATE) == _get_episode_id(DATE)


# ── 게이트 판정 ──────────────────────────────────────────────


def _patch_loaders(monkeypatch, episode_row, analysis_row=None, video_row=None):
    monkeypatch.setattr(sp, "_load_latest_episode_row", lambda d: episode_row)
    monkeypatch.setattr(sp, "_load_analysis_row", lambda d: analysis_row)
    monkeypatch.setattr(sp, "_load_video_asset_row", lambda e: video_row)


def _battle_row(event_type="BATTLE", scenario_type="ONE_VS_ONE"):
    return {
        "episode_date": DATE,
        "event_type": event_type,
        "scenario_type": scenario_type,
        "script_json": {"panels": []},
        "battle_json": {"outcome": "HERO_TACTICAL_VICTORY", "villain_id": "CHAR_VILLAIN_001"},
        "heroes_json": ["CHAR_HERO_001"],
    }


def test_gate_pass_major_battle(monkeypatch):
    _patch_loaders(monkeypatch, _battle_row())
    result = run_gate(DATE)
    assert result.passed is True
    assert result.reason == "major_battle"
    assert result.event_type == "BATTLE"


@pytest.mark.parametrize("event_type", ["NORMAL", "INTEL", "FLASHBACK", ""])
def test_gate_blocks_non_major(monkeypatch, event_type):
    _patch_loaders(monkeypatch, _battle_row(event_type=event_type))
    result = run_gate(DATE)
    assert result.passed is False
    assert result.reason.startswith("non_major_event")


def test_gate_blocks_no_battle(monkeypatch):
    _patch_loaders(monkeypatch, _battle_row(event_type="SHOCK", scenario_type="NO_BATTLE"))
    result = run_gate(DATE)
    assert result.passed is False
    assert result.reason == "no_battle_scenario"


def test_gate_blocks_missing_episode(monkeypatch):
    _patch_loaders(monkeypatch, None)
    result = run_gate(DATE)
    assert result.passed is False
    assert result.reason == "episode_assets_not_found"


def test_gate_blocks_missing_script(monkeypatch):
    row = _battle_row()
    row["script_json"] = None
    _patch_loaders(monkeypatch, row)
    assert run_gate(DATE).reason == "script_json_missing"


def test_gate_idempotent_when_published(monkeypatch):
    _patch_loaders(
        monkeypatch,
        _battle_row(),
        video_row={"episode_id": build_shorts_episode_id(DATE), "status": "published"},
    )
    result = run_gate(DATE)
    assert result.passed is False
    assert result.reason == "already_published"


def test_gate_result_json_excludes_rows(monkeypatch):
    _patch_loaders(monkeypatch, _battle_row())
    payload = run_gate(DATE).to_json()
    assert "episode_row" not in payload
    assert "analysis_row" not in payload
    assert payload["passed"] is True


# ── Immutable Facts 추출 ─────────────────────────────────────


def _passed_gate(row=None, analysis=None):
    return GateResult(
        passed=True,
        reason="major_battle",
        episode_date=DATE,
        episode_id=build_shorts_episode_id(DATE),
        event_type="BATTLE",
        scenario_type="ONE_VS_ONE",
        episode_row=row if row is not None else _battle_row(),
        analysis_row=analysis,
    )


def test_extract_facts_from_battle_json():
    facts = extract_immutable_facts(_passed_gate())
    assert facts["outcome"] == "HERO_TACTICAL_VICTORY"
    assert facts["hero_ids"] == ["CHAR_HERO_001"]
    assert facts["villain_id"] == "CHAR_VILLAIN_001"


def test_extract_facts_villain_fallback_to_analysis():
    row = _battle_row()
    row["battle_json"] = {"outcome": "DRAW"}
    facts = extract_immutable_facts(
        _passed_gate(row=row, analysis={"selected_villain_id": "CHAR_VILLAIN_002"})
    )
    assert facts["villain_id"] == "CHAR_VILLAIN_002"


def test_extract_facts_incomplete_raises():
    row = _battle_row()
    row["battle_json"] = {}
    row["heroes_json"] = []
    with pytest.raises(sp.ShortsPipelineError, match="Immutable Facts"):
        extract_immutable_facts(_passed_gate(row=row))


# ── ShortsScenario 스키마 + Consistency Guard ────────────────


def _scenario_dict(**overrides):
    cut = {
        "seq": 1,
        "caption": "금리 하락",
        "narration_tts": "국채금리가 내려가며 전선이 열립니다.",
        "video_prompt": "Cinematic vertical full shot of tiger warrior, Manhwa style, 9:16.",
        "duration_sec": 8,
    }
    base = {
        "episode_id": build_shorts_episode_id(DATE),
        "episode_date": DATE,
        "event_type": "BATTLE",
        "scenario_type": "ONE_VS_ONE",
        "outcome": "HERO_TACTICAL_VICTORY",
        "hero_ids": ["CHAR_HERO_001"],
        "villain_id": "CHAR_VILLAIN_001",
        "intro": {
            "caption": "오늘의 전투",
            "narration_tts": "시장의 수호자가 움직입니다.",
            "image_prompt": "Vertical 9:16 heroic intro card, Manhwa style, no text.",
        },
        "cuts": [
            {**cut, "seq": 1},
            {**cut, "seq": 2},
            {**cut, "seq": 3},
        ],
        "outro": {
            "caption": "다음 화 예고",
            "narration_tts": "투자 참고 정보이며, 투자 권유가 아닙니다.",
            "image_prompt": "Vertical 9:16 outro card with sunrise city, Manhwa style.",
        },
        "youtube_title": "부채 타이탄 격파",
        "youtube_description": "투자 참고 정보이며, 투자 권유가 아닙니다.",
    }
    base.update(overrides)
    return base


def test_scenario_schema_valid():
    scenario = ShortsScenario(**_scenario_dict())
    assert scenario.total_duration_sec() == 8 * 3 + 3 * 2  # 30초


def test_scenario_rejects_wrong_seq_order():
    data = _scenario_dict()
    data["cuts"][0]["seq"] = 2
    data["cuts"][1]["seq"] = 1
    with pytest.raises(ValueError, match="seq"):
        ShortsScenario(**data)


def test_scenario_rejects_two_cuts():
    data = _scenario_dict()
    data["cuts"] = data["cuts"][:2]
    with pytest.raises(ValueError):
        ShortsScenario(**data)


def test_consistency_guard_outcome_mismatch():
    scenario = ShortsScenario(**_scenario_dict())
    with pytest.raises(ConsistencyGuardError, match="outcome"):
        enforce_consistency(
            scenario,
            outcome="VILLAIN_VICTORY",
            hero_ids=["CHAR_HERO_001"],
            villain_id="CHAR_VILLAIN_001",
        )


def test_consistency_guard_villain_mismatch():
    scenario = ShortsScenario(**_scenario_dict())
    with pytest.raises(ConsistencyGuardError, match="villain"):
        enforce_consistency(
            scenario,
            outcome="HERO_TACTICAL_VICTORY",
            hero_ids=["CHAR_HERO_001"],
            villain_id="CHAR_VILLAIN_009",
        )


def test_consistency_guard_pass():
    scenario = ShortsScenario(**_scenario_dict())
    enforce_consistency(
        scenario,
        outcome="HERO_TACTICAL_VICTORY",
        hero_ids=["CHAR_HERO_001"],
        villain_id="CHAR_VILLAIN_001",
    )


# ── 각색 DRY_RUN ─────────────────────────────────────────────


def test_generate_dry_run_skips_claude(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    scenario, cost = generate_shorts_scenario(_passed_gate())
    assert scenario is None
    assert cost == 0.0


def test_generate_refuses_unpassed_gate():
    gate = GateResult(
        passed=False,
        reason="no_battle_scenario",
        episode_date=DATE,
        episode_id=build_shorts_episode_id(DATE),
    )
    with pytest.raises(sp.ShortsPipelineError, match="gate 미통과"):
        generate_shorts_scenario(gate, dry_run=True)


# ── Claude SDK 호환 (2026-08-29 run #33229450042 회고) ──────


def test_generate_uses_sdk_compat_kwargs_without_temperature(monkeypatch, tmp_path):
    """SDK 1.0(temperature 미지원)에서도 create 호출이 성공해야 한다."""
    import json as _json
    import sys
    import types

    captured = {}

    class _FakeMessages:
        # SDK 1.0 시그니처: temperature 없음
        def create(self, *, model, max_tokens, system, messages):
            captured["kwargs"] = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            }
            payload = _scenario_dict()
            block = types.SimpleNamespace(type="text", text=_json.dumps(payload))
            usage = types.SimpleNamespace(input_tokens=100, output_tokens=200)
            return types.SimpleNamespace(content=[block], usage=usage)

    class _FakeAnthropic:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_FakeAnthropic)
    )
    monkeypatch.setenv("DRY_RUN", "false")

    scenario, cost = generate_shorts_scenario(_passed_gate())

    assert scenario is not None
    assert "temperature" not in captured["kwargs"]  # SDK 1.0 호환
    assert captured["kwargs"]["model"] == "claude-sonnet-4-6"
    assert captured["kwargs"]["system"]
    assert cost > 0
