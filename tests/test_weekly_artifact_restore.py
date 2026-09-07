"""tests/test_weekly_artifact_restore.py — 선행 artifact 복원 해석 (DB 미사용).

배경: 2026-09-07 run #34101547854 에서 미디어 생성 후 조립이 스킵되자, 새 러너에
      파일이 없어 재조립이 불가능했다. 복구 수단이 전체 재생성($1.88)뿐이었다.
"""

from __future__ import annotations

import types

import pytest

import scripts.resolve_weekly_artifact as rwa

EID = "icg-vw-2026-W36-001"


def _patch(monkeypatch, row):
    import sys

    fake = types.ModuleType("engine.video.weekly_pipeline")
    fake._load_video_asset_row = lambda e: row
    fake.build_weekly_episode_id = lambda d: EID
    fake.resolve_week_window = lambda *a, **k: ("2026-08-31", "2026-09-06")
    monkeypatch.setitem(sys.modules, "engine.video.weekly_pipeline", fake)


@pytest.mark.parametrize(
    "status", ["media_generated", "assembled", "pending_approval"]
)
def test_restores_when_media_exists(monkeypatch, status):
    _patch(monkeypatch, {"status": status, "artifact_run_id": "34101547854"})
    target = rwa.resolve()
    assert target is not None
    assert target["run_id"] == "34101547854"
    assert target["episode_id"] == EID


@pytest.mark.parametrize("status", ["gated", "scenario_ready", "skipped"])
def test_no_restore_before_media_generated(monkeypatch, status):
    """생성 전 상태는 복원할 산출물이 없다."""
    _patch(monkeypatch, {"status": status, "artifact_run_id": "123"})
    assert rwa.resolve() is None


def test_no_restore_for_new_week(monkeypatch):
    _patch(monkeypatch, None)
    assert rwa.resolve() is None


def test_raises_when_media_exists_but_run_id_missing(monkeypatch):
    """v1.1.0: 조용히 넘기면 W6 이 엉뚱한 사유로 실패한다 → 즉시 알린다."""
    _patch(monkeypatch, {"status": "media_generated", "artifact_run_id": None})
    with pytest.raises(rwa.RestoreUnavailableError, match="artifact_run_id"):
        rwa.resolve()


def test_main_fails_when_restore_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    monkeypatch.chdir(tmp_path)

    def _boom():
        raise rwa.RestoreUnavailableError("no run id")

    monkeypatch.setattr(rwa, "resolve", _boom)
    assert rwa.main() == 1  # 조용히 통과하지 않는다


def test_main_writes_artifact_log(monkeypatch, tmp_path):
    """판단 근거가 artifact(logs/)에 남아야 원인 규명이 가능하다."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rwa, "resolve", lambda: None)
    rwa.main()
    log = tmp_path / "logs" / "999" / "resolve_artifact.log"
    assert log.exists()
    assert "resolve_weekly_artifact" in log.read_text(encoding="utf-8")


def test_main_emits_found_true(monkeypatch, tmp_path):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(
        rwa, "resolve", lambda: {"episode_id": EID, "run_id": "34101547854"}
    )
    assert rwa.main() == 0
    content = out.read_text()
    assert "found=true" in content
    assert "run_id=34101547854" in content


def test_main_emits_found_false(monkeypatch, tmp_path):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(rwa, "resolve", lambda: None)
    assert rwa.main() == 0
    assert "found=false" in out.read_text()


def test_main_fails_loudly_on_db_error(monkeypatch, tmp_path):
    """v1.1.0: 조회 실패를 found=false 로 숨기면 W6 실패 원인이 가려진다."""
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.chdir(tmp_path)

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(rwa, "resolve", _boom)
    assert rwa.main() == 1


def test_workflow_restores_before_assembly():
    """복원 step 이 W6 조립보다 앞에 있어야 의미가 있다."""
    from pathlib import Path

    import yaml

    path = Path(".github/workflows/run_weekly_shorts.yml")
    if not path.exists():
        pytest.skip("워크플로 파일 없음")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = [str(s.get("name", "")) for s in data["jobs"]["weekly_digest"]["steps"]]
    restore_idx = next(i for i, n in enumerate(names) if "Restore prior media" in n)
    assembly_idx = next(i for i, n in enumerate(names) if "W6 assembly" in n)
    assert restore_idx < assembly_idx


# ── v1.3.0 SELECT 컬럼 누락 회귀 (2026-09-07 run #34117473966) ──
# 증상: _load_video_asset_row 가 episode_id/status/youtube_video_id 만 SELECT 해
#       artifact_run_id 가 항상 None → "복원 불가" 오판 → 재조립 실패.


@pytest.mark.parametrize(
    "module_path",
    ["engine/video/weekly_pipeline.py", "engine/video/shorts_pipeline.py"],
)
def test_video_asset_select_includes_consumed_columns(module_path):
    """소비처가 읽는 컬럼이 SELECT 에 모두 포함되어야 한다."""
    from pathlib import Path

    src = Path(module_path)
    if not src.exists():
        pytest.skip(f"{module_path} 없음")
    text = src.read_text(encoding="utf-8")
    start = text.index("def _load_video_asset_row")
    body = text[start : start + 900]
    for col in ("artifact_run_id", "veo_cost_usd", "status", "youtube_video_id"):
        assert col in body, f"{module_path}: SELECT 에 {col} 누락"
