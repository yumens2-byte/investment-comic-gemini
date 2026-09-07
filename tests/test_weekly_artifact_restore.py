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


def test_no_restore_when_run_id_missing(monkeypatch):
    """artifact_run_id 가 없으면 복원 불가 — 조용히 건너뛰어야 한다."""
    _patch(monkeypatch, {"status": "media_generated", "artifact_run_id": None})
    assert rwa.resolve() is None


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


def test_main_survives_db_error(monkeypatch, tmp_path):
    """복원 해석 실패가 파이프라인 전체를 막으면 안 된다 (신규 생성은 계속 가능)."""
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(rwa, "resolve", _boom)
    assert rwa.main() == 0
    assert "found=false" in out.read_text()


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
