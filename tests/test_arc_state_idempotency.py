"""2026-09-04 발견: 동일 날짜 재실행 시 arc 시계 중복 진행 방지 회귀 테스트."""

from datetime import datetime, timezone

from engine.arc.arc_state_engine import update_after_episode

_SNAPSHOT = {"fear_greed": 65, "vix": 15.2}


def _state(last_date: str | None):
    return {
        "active_villain": "CHAR_VILLAIN_004",
        "arc_day": 41,
        "villain_streak": 41,
        "season_arc_days": 41,
        "arc_tension": 6,
        "hero_momentum": 100,
        "last_episode_date": last_date,
        "open_hook": "이전 hook",
        "last_outcome": "PEACEFUL_GROWTH",
        "last_episode_type": "FLASHBACK",
    }


def test_same_day_rerun_does_not_advance_clock() -> None:
    today = datetime.now(tz=timezone.utc).date().isoformat()
    updated = update_after_episode(
        _state(today), "PEACEFUL_GROWTH", "FLASHBACK", _SNAPSHOT,
        open_hook="새 hook",
    )

    assert updated["arc_day"] == 41
    assert updated["villain_streak"] == 41
    assert updated["arc_tension"] == 6  # outcome delta 미중복
    assert updated["open_hook"] == "새 hook"  # 최신 에피소드 내용은 반영


def test_new_day_advances_clock() -> None:
    updated = update_after_episode(
        _state("2020-01-01"), "PEACEFUL_GROWTH", "FLASHBACK", _SNAPSHOT,
        open_hook="새 hook",
    )

    assert updated["arc_day"] == 42
    assert updated["villain_streak"] == 42


def test_villain_change_bypasses_guard() -> None:
    today = datetime.now(tz=timezone.utc).date().isoformat()
    updated = update_after_episode(
        _state(today), "HERO_VICTORY", "EMERGENCE", _SNAPSHOT,
        new_villain="CHAR_VILLAIN_002",
    )

    assert updated["active_villain"] == "CHAR_VILLAIN_002"
    assert updated["arc_day"] == 1  # 정당한 리셋은 가드와 무관하게 수행
