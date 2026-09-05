"""tests/test_weekly_pipeline.py — 주간 다이제스트 (DB/API 미사용)."""

from __future__ import annotations

import sys
import types
from datetime import date

import pytest

from engine.video import weekly_pipeline as wp
from engine.video.shorts_pipeline import ShortsScenario

# ── 주간 구간 계산 ───────────────────────────────────────────


def test_window_from_monday_returns_previous_iso_week():
    """월요일 오전 실행 = 지난주 월~일 (정규 경로)."""
    start, end = wp.resolve_week_window(date(2026, 8, 31))  # 월
    assert start == date(2026, 8, 24)
    assert end == date(2026, 8, 30)
    assert start.weekday() == 0 and end.weekday() == 6


@pytest.mark.parametrize("day", [1, 2, 3, 4, 5, 6])
def test_window_stable_within_same_week(day):
    """화~일 수동 재실행해도 같은 지난주 구간이 나와야 한다 (멱등)."""
    from datetime import timedelta

    monday = date(2026, 8, 31)
    base = wp.resolve_week_window(monday)
    assert wp.resolve_week_window(monday + timedelta(days=day)) == base


def test_window_spans_full_week():
    start, end = wp.resolve_week_window(date(2026, 8, 31))
    assert (end - start).days == 6  # 월~일


def test_window_includes_saturday_episode():
    """v1.1.0 회고: 토요일 episode_date = 금요일 미국장. 월~금 창은 이를 누락했다.

    2026-09-05 실측: 이번 주 에피소드가 9/4(금), 9/5(토) 뿐이라 구 창(월~금)으론
    1건 → 게이트 미달. 새 창(월~일)은 2건 → 통과.
    """
    start, end = wp.resolve_week_window(date(2026, 9, 7))  # 다음 월요일 실행
    saturday = date(2026, 9, 5)
    assert start <= saturday <= end


def test_weekly_episode_id_format():
    eid = wp.build_weekly_episode_id(date(2026, 8, 28))
    assert eid.startswith("icg-vw-")
    assert "W35" in eid
    # 일일 트랙과 접두사로 구분되어야 한다 (중복 방지)
    assert not eid.startswith("icg-v-2")


# ── 게이트 ───────────────────────────────────────────────────


def _ep(d: str, event_type: str = "BATTLE"):
    return {
        "episode_date": d,
        "event_type": event_type,
        "scenario_type": "NO_BATTLE",  # 실데이터 재현: 전부 NO_BATTLE
        "script_json": {"panels": []},
        "battle_json": {"outcome": "DRAW", "villain_id": "CHAR_VILLAIN_004"},
        "heroes_json": ["CHAR_HERO_001"],
    }


def _patch(monkeypatch, episodes, video_row=None):
    monkeypatch.setattr(wp, "_load_week_episodes", lambda s, e: episodes)
    monkeypatch.setattr(wp, "_load_video_asset_row", lambda e: video_row)


def test_gate_passes_regardless_of_no_battle(monkeypatch):
    """확정 정책: 주간 게이트는 전투 유무가 아니라 에피소드 수로 판정한다."""
    monkeypatch.delenv("FORCE_REGENERATE", raising=False)
    _patch(monkeypatch, [_ep("2026-08-24"), _ep("2026-08-26", "INTEL")])
    gate = wp.run_weekly_gate(date(2026, 8, 31))
    assert gate.passed is True
    assert gate.episode_count == 2
    assert gate.battle_count == 1


def test_gate_blocks_insufficient_episodes(monkeypatch):
    monkeypatch.delenv("FORCE_REGENERATE", raising=False)
    _patch(monkeypatch, [_ep("2026-08-24")])
    gate = wp.run_weekly_gate(date(2026, 8, 31))
    assert gate.passed is False
    assert gate.reason.startswith("insufficient_episodes")


def test_gate_ignores_episodes_without_script(monkeypatch):
    monkeypatch.delenv("FORCE_REGENERATE", raising=False)
    bad = _ep("2026-08-25")
    bad["script_json"] = None
    _patch(monkeypatch, [_ep("2026-08-24"), bad])
    assert wp.run_weekly_gate(date(2026, 8, 31)).passed is False


def test_gate_blocks_already_published(monkeypatch):
    _patch(
        monkeypatch,
        [_ep("2026-08-24"), _ep("2026-08-25")],
        video_row={"status": "published", "youtube_video_id": "abc"},
    )
    assert wp.run_weekly_gate(date(2026, 8, 31)).reason == "already_published"


@pytest.mark.parametrize("spent", ["media_generated", "assembled", "pending_approval"])
def test_gate_blocks_already_generated(monkeypatch, spent):
    """중복 과금 방지 — 주간도 동일 정책."""
    monkeypatch.delenv("FORCE_REGENERATE", raising=False)
    _patch(
        monkeypatch,
        [_ep("2026-08-24"), _ep("2026-08-25")],
        video_row={"status": spent, "youtube_video_id": None},
    )
    assert wp.run_weekly_gate(date(2026, 8, 31)).reason == f"already_generated:{spent}"


def test_gate_force_regenerate(monkeypatch):
    monkeypatch.setenv("FORCE_REGENERATE", "true")
    _patch(
        monkeypatch,
        [_ep("2026-08-24"), _ep("2026-08-25")],
        video_row={"status": "assembled", "youtube_video_id": None},
    )
    assert wp.run_weekly_gate(date(2026, 8, 31)).passed is True


def test_gate_json_excludes_raw_episodes(monkeypatch):
    monkeypatch.delenv("FORCE_REGENERATE", raising=False)
    _patch(monkeypatch, [_ep("2026-08-24"), _ep("2026-08-25")])
    payload = wp.run_weekly_gate(date(2026, 8, 31)).to_json()
    assert "episodes" not in payload
    assert payload["episode_count"] == 2


# ── Immutable Facts ──────────────────────────────────────────


def _passed_gate(episodes=None):
    return wp.WeeklyGateResult(
        True,
        "weekly_digest",
        "icg-vw-2026-W35-001",
        "2026-08-24",
        "2026-08-28",
        episode_count=2,
        battle_count=2,
        episodes=episodes or [_ep("2026-08-24"), _ep("2026-08-25")],
    )


def test_facts_collect_unique_characters():
    ep2 = _ep("2026-08-25")
    ep2["heroes_json"] = ["CHAR_HERO_003"]
    facts = wp.extract_weekly_facts(_passed_gate([_ep("2026-08-24"), ep2]))
    assert facts["hero_ids"] == ["CHAR_HERO_001", "CHAR_HERO_003"]
    assert facts["villain_id"] == "CHAR_VILLAIN_004"
    assert len(facts["weekly_beats"]) == 2


def test_facts_raise_without_heroes():
    ep = _ep("2026-08-24")
    ep["heroes_json"] = []
    with pytest.raises(wp.WeeklyPipelineError, match="히어로"):
        wp.extract_weekly_facts(_passed_gate([ep]))


# ── 18초 규격 강제 ───────────────────────────────────────────


def _weekly_scenario_dict(**over):
    cut = {
        "caption": "주 초반 급락",
        "narration_tts": "국채금리 급등에 시장이 흔들립니다",  # 19자
        "video_prompt": (
            "Cinematic vertical 9:16 Manhwa. Anthropomorphic Bengal tiger-headed hero "
            "in navy bodysuit with gold D emblem and chainsaw faces a five-headed hydra."
        ),
        "duration_sec": 6,
    }
    base = {
        "episode_id": "icg-vw-2026-W35-001",
        "episode_date": "2026-08-28",
        "event_type": "WEEKLY_DIGEST",
        "scenario_type": "DIGEST",
        "outcome": "WEEKLY_SUMMARY",
        "hero_ids": ["CHAR_HERO_001"],
        "villain_id": "CHAR_VILLAIN_004",
        "intro": {
            "caption": "이번 주 시장",
            "narration_tts": "한 주의 전장입니다",  # 10자
            "image_prompt": "Vertical 9:16 Manhwa weekly digest title card, tiger hero.",
        },
        "cuts": [{**cut, "seq": 1}, {**cut, "seq": 2}],
        "outro": {
            "caption": "다음 주 예고",
            "narration_tts": "투자 참고, 권유 아님",  # 12자
            "image_prompt": "Vertical 9:16 Manhwa outro card with sunrise city.",
        },
        "youtube_title": "이번 주 시장 다이제스트",
        "youtube_description": "투자 참고 정보이며, 투자 권유가 아닙니다.",
    }
    base.update(over)
    return base


def test_weekly_scenario_is_exactly_18s():
    sc = ShortsScenario(**_weekly_scenario_dict())
    wp.enforce_weekly_limits(sc)
    assert sc.total_duration_sec() == wp.WEEKLY_TOTAL_SEC == 18


def test_weekly_limits_reject_three_cuts():
    data = _weekly_scenario_dict()
    data["cuts"] = data["cuts"] + [{**data["cuts"][0], "seq": 3}]
    with pytest.raises(ValueError, match="2컷 고정"):
        wp.enforce_weekly_limits(ShortsScenario(**data))


def test_weekly_limits_reject_wrong_duration():
    data = _weekly_scenario_dict()
    for c in data["cuts"]:
        c["duration_sec"] = 8
    with pytest.raises(ValueError, match="6초 고정"):
        wp.enforce_weekly_limits(ShortsScenario(**data))


def test_weekly_limits_reject_overlong_cut_narration():
    data = _weekly_scenario_dict()
    data["cuts"][0]["narration_tts"] = "가" * (wp.WEEKLY_CUT_NARRATION_MAX + 1)
    with pytest.raises(ValueError, match="나레이션"):
        wp.enforce_weekly_limits(ShortsScenario(**data))


def test_weekly_limits_reject_overlong_bookend_narration():
    """북엔드가 15자를 넘으면 3초를 초과해 18초 규격이 깨진다."""
    data = _weekly_scenario_dict()
    data["outro"]["narration_tts"] = "가" * (wp.WEEKLY_BOOKEND_NARRATION_MAX + 1)
    with pytest.raises(ValueError, match="18초 규격 초과"):
        wp.enforce_weekly_limits(ShortsScenario(**data))


def test_bookend_limit_keeps_three_seconds():
    """상한 글자수가 실제로 3초 북엔드를 보장하는지 조립 로직과 교차 검증."""
    from engine.video.shorts_media import bookend_duration

    assert bookend_duration("가" * wp.WEEKLY_BOOKEND_NARRATION_MAX) == wp.WEEKLY_BOOKEND_SEC


# ── 각색 ─────────────────────────────────────────────────────


def test_generate_dry_run_skips_claude(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    scenario, cost = wp.generate_weekly_scenario(_passed_gate())
    assert scenario is None
    assert cost == 0.0


def test_generate_refuses_unpassed_gate():
    gate = wp.WeeklyGateResult(False, "insufficient_episodes:1<2", "x", "a", "b")
    with pytest.raises(wp.WeeklyPipelineError, match="gate 미통과"):
        wp.generate_weekly_scenario(gate, dry_run=True)


def test_weekly_prompt_embeds_canon_and_limits():
    facts = wp.extract_weekly_facts(_passed_gate())
    prompt = wp._build_weekly_prompt(facts, _passed_gate().episodes)
    assert "tiger" in prompt.lower()  # Canon 종족
    assert str(wp.WEEKLY_CUT_NARRATION_MAX) in prompt
    assert str(wp.WEEKLY_BOOKEND_NARRATION_MAX) in prompt
    assert "WEEKLY_DIGEST" in prompt


def test_generate_uses_sdk_compat_and_validates(monkeypatch):
    """SDK 호환 + 주간 규격 검증이 실제 각색 경로에서 동작해야 한다."""
    import json as _json

    captured = {}

    class _Messages:
        def create(self, *, model, max_tokens, system, messages):
            captured["ok"] = True
            block = types.SimpleNamespace(
                type="text", text=_json.dumps(_weekly_scenario_dict())
            )
            usage = types.SimpleNamespace(input_tokens=500, output_tokens=400)
            return types.SimpleNamespace(content=[block], usage=usage)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Anthropic))
    monkeypatch.setenv("DRY_RUN", "false")

    scenario, cost = wp.generate_weekly_scenario(_passed_gate())
    assert scenario is not None
    assert len(scenario.cuts) == 2
    assert scenario.total_duration_sec() == 18
    assert cost > 0
    assert captured["ok"]
