"""tests/test_shorts_release.py — 지연 자동발행(hold-and-release) 대상 선택 (DB 미사용)."""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta

import pytest

import scripts.resolve_shorts_release as rsr

EID = "icg-v-2026-04-22-001"


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def is_(self, key, value):
        self.filters[f"is_{key}"] = value
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        rows = self._rows
        if "episode_id" in self.filters:
            rows = [r for r in rows if r["episode_id"] == self.filters["episode_id"]]
        return types.SimpleNamespace(data=rows)


def _patch_table(monkeypatch, table_factory):
    """engine.common.supabase_client 를 가짜 모듈로 대체.

    resolve() 가 함수 내부에서 import 하므로 sys.modules 주입으로 충분하며,
    supabase 패키지가 설치되지 않은 환경에서도 테스트가 동작한다.
    """
    import sys

    fake = types.ModuleType("engine.common.supabase_client")
    fake.icg_table = table_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "engine.common.supabase_client", fake)


def _row(**over):
    base = {
        "episode_id": EID,
        "episode_date": "2026-04-22",
        "status": "pending_approval",
        "release_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "artifact_run_id": "33229690192",
        "youtube_video_id": None,
    }
    base.update(over)
    return base


def test_selects_row_past_release_time(monkeypatch):
    _patch_table(monkeypatch, lambda _n: _FakeQuery([_row()]))
    picked = rsr.resolve()
    assert picked is not None
    assert picked["episode_id"] == EID


def test_skips_row_still_on_hold(monkeypatch):
    """홀드 중인 건은 절대 발행 대상이 되면 안 된다 (마스터 검토 시간 보장)."""
    future = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    _patch_table(monkeypatch, lambda _n: _FakeQuery([_row(release_at=future)]))
    assert rsr.resolve() is None


def test_skips_row_without_release_at(monkeypatch):
    _patch_table(monkeypatch, lambda _n: _FakeQuery([_row(release_at=None)]))
    assert rsr.resolve() is None


def test_skips_row_without_artifact(monkeypatch):
    """mp4 복원 불가 건을 선택하면 발행 job 이 실패하므로 미리 제외."""
    _patch_table(monkeypatch, lambda _n: _FakeQuery([_row(artifact_run_id=None)]))
    assert rsr.resolve() is None


def test_returns_none_when_no_rows(monkeypatch):
    _patch_table(monkeypatch, lambda _n: _FakeQuery([]))
    assert rsr.resolve() is None


def test_picks_first_released_among_mixed(monkeypatch):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    rows = [
        _row(episode_id="icg-v-2026-04-23-001", release_at=future),
        _row(),
    ]
    _patch_table(monkeypatch, lambda _n: _FakeQuery(rows))
    picked = rsr.resolve()
    assert picked["episode_id"] == EID


def test_query_filters_exclude_published(monkeypatch):
    """중복 발행 차단: status/youtube_video_id 필터가 실제로 적용되어야 한다."""
    captured = {}

    class _Capture(_FakeQuery):
        def execute(self):
            captured.update(self.filters)
            return super().execute()

    _patch_table(monkeypatch, lambda _n: _Capture([_row()]))
    rsr.resolve()
    assert captured["status"] == "pending_approval"
    assert captured["is_youtube_video_id"] == "null"


def test_emit_writes_github_output(monkeypatch, tmp_path):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    rsr._emit(found="true", episode_id=EID, episode_date="2026-04-22", artifact_run_id="1")
    content = out.read_text()
    assert "found=true" in content
    # 러너는 YYYY-MM-DD 를 기대한다 (episode_id 전달 시 날짜 파싱 실패)
    assert "episode_date=2026-04-22" in content


def test_main_exits_zero_when_no_target(monkeypatch, tmp_path):
    """대상 없음은 스케줄 실행의 정상 케이스 — 실패로 처리하면 알림 스팸이 된다."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    monkeypatch.setattr(rsr, "resolve", lambda *_a, **_k: None)
    monkeypatch.setattr("sys.argv", ["resolve_shorts_release"])
    assert rsr.main() == 0


def test_main_exits_one_on_db_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))

    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rsr, "resolve", _boom)
    monkeypatch.setattr("sys.argv", ["resolve_shorts_release"])
    assert rsr.main() == 1


# ── 캡션: hold-and-release 안내 ──────────────────────────────


def test_caption_shows_auto_publish_when_release_given():
    from engine.publish.telegram_gate import _build_caption

    cap = _build_caption(EID, "ALLIANCE", 3.72, 190000, 23.4, release_at_kst="04/22 09:17")
    assert "자동 발행" in cap
    assert "04/22 09:17" in cap
    assert "abort" in cap
    assert "2026-04-22" in cap  # 중단 명령용 target_date


def test_caption_falls_back_to_manual_approval():
    from engine.publish.telegram_gate import _build_caption

    cap = _build_caption(EID, "ALLIANCE", 3.72, 190000, 23.4)
    assert "승인 방법" in cap
    assert "publish" in cap


@pytest.mark.parametrize("hold", ["1", "6", "12"])
def test_release_at_respects_hold_env(monkeypatch, hold):
    """PUBLISH_HOLD_HOURS 로 검토 시간을 조절할 수 있어야 한다."""
    monkeypatch.setenv("PUBLISH_HOLD_HOURS", hold)
    hours = float(__import__("os").environ["PUBLISH_HOLD_HOURS"])
    release = datetime.now(UTC) + timedelta(hours=hours)
    assert (release - datetime.now(UTC)).total_seconds() == pytest.approx(
        hours * 3600, abs=5
    )
