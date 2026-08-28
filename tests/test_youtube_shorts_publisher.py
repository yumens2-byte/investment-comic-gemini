"""tests/test_youtube_shorts_publisher.py — v1.1.0 단위 테스트 (네트워크 미사용)."""

from __future__ import annotations

import pytest

from engine.publish.youtube_shorts_publisher import (
    MAX_DESCRIPTION_LEN,
    MAX_TITLE_LEN,
    YouTubeShortsPublishError,
    _is_dry_run,
    build_shorts_metadata,
    publish_to_youtube_shorts,
)

# ── build_shorts_metadata ───────────────────────────────────────


def test_metadata_appends_shorts_tag():
    body = build_shorts_metadata("오늘의 전투", "설명")
    assert body["snippet"]["title"].endswith("#Shorts")


def test_metadata_keeps_existing_shorts_tag():
    body = build_shorts_metadata("오늘의 전투 #Shorts", "설명")
    assert body["snippet"]["title"].count("#Shorts") == 1


def test_metadata_truncates_long_title():
    body = build_shorts_metadata("가" * 300, "설명")
    assert len(body["snippet"]["title"]) <= MAX_TITLE_LEN


def test_metadata_truncates_long_description():
    body = build_shorts_metadata("t", "나" * 6000)
    assert len(body["snippet"]["description"]) <= MAX_DESCRIPTION_LEN


def test_metadata_defaults():
    body = build_shorts_metadata("t", "d")
    assert body["snippet"]["categoryId"] == "25"
    assert body["status"]["privacyStatus"] == "public"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["snippet"]["tags"] == []


# ── DRY_RUN 판정 (공통 지침 통일 규약) ──────────────────────────


def test_dry_run_default_true_when_env_missing(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert _is_dry_run() is True


def test_dry_run_empty_string_treated_as_not_true(monkeypatch):
    # 규약: .lower() == "true" 판정식 — 빈 문자열은 False (발행 계층과 동일 동작)
    monkeypatch.setenv("DRY_RUN", "")
    assert _is_dry_run() is False


def test_dry_run_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    assert _is_dry_run(dry_run=True) is True


# ── publish_to_youtube_shorts ───────────────────────────────────


def _set_required_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")


def test_publish_missing_file_raises(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    with pytest.raises(YouTubeShortsPublishError, match="video_path not found"):
        publish_to_youtube_shorts(
            video_path=str(tmp_path / "nope.mp4"),
            title="t",
            description="d",
            episode_id="icg-v-2026-08-29-001",
            dry_run=True,
        )


@pytest.mark.parametrize(
    "missing", ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
)
def test_publish_missing_env_raises(monkeypatch, tmp_path, missing):
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"00")
    with pytest.raises(YouTubeShortsPublishError, match=missing):
        publish_to_youtube_shorts(
            video_path=str(video),
            title="t",
            description="d",
            episode_id="icg-v-2026-08-29-001",
            dry_run=True,
        )


def test_publish_dry_run_skips_upload(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"00")
    result = publish_to_youtube_shorts(
        video_path=str(video),
        title="배틀 쇼츠",
        description="d",
        episode_id="icg-v-2026-08-29-001",
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["youtube_video_id"] is None
    assert result["quota_units"] == 0
