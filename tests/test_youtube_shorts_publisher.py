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


# ── v1.2.0 자격증명 검증 (2026-08-29 run #33240050576 회고) ──
# 증상: 업로드 중 google.auth RefreshError(invalid_grant) 가 원시 트레이스백으로 노출.


def test_token_shape_hint_detects_access_token(monkeypatch):
    from engine.publish.youtube_shorts_publisher import _refresh_token_shape_hint

    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ya29.a0AfB_abcdef")
    assert "액세스 토큰" in _refresh_token_shape_hint()


def test_token_shape_hint_detects_auth_code(monkeypatch):
    from engine.publish.youtube_shorts_publisher import _refresh_token_shape_hint

    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "4/0AeanS0abcdef")
    assert "인가 코드" in _refresh_token_shape_hint()


def test_token_shape_hint_detects_whitespace(monkeypatch):
    from engine.publish.youtube_shorts_publisher import _refresh_token_shape_hint

    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "1//0abcdef\n")
    assert "공백" in _refresh_token_shape_hint()


def test_token_shape_hint_clean_for_valid_prefix(monkeypatch):
    from engine.publish.youtube_shorts_publisher import _refresh_token_shape_hint

    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "1//0abcdefGHIJK")
    assert _refresh_token_shape_hint() == ""


def test_verify_returns_invalid_on_refresh_failure(monkeypatch):
    """invalid_grant 시 예외가 아니라 진단 결과를 돌려줘야 한다 (안내 로그 포함)."""
    import sys
    import types

    from engine.publish import youtube_shorts_publisher as ysp

    _set_required_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "1//broken")

    class _Creds:
        def __init__(self, *a, **k):
            pass

        def refresh(self, _request):
            raise RuntimeError("invalid_grant: Bad Request")

    monkeypatch.setitem(
        sys.modules,
        "google.oauth2.credentials",
        types.SimpleNamespace(Credentials=_Creds),
    )
    monkeypatch.setitem(
        sys.modules,
        "google.auth.transport.requests",
        types.SimpleNamespace(Request=lambda: object()),
    )

    result = ysp.verify_youtube_credentials()
    assert result["valid"] is False
    assert "invalid_grant" in result["detail"]


def test_verify_returns_valid_on_success(monkeypatch):
    import sys
    import types

    from engine.publish import youtube_shorts_publisher as ysp

    _set_required_env(monkeypatch)

    class _Creds:
        def __init__(self, *a, **k):
            pass

        def refresh(self, _request):
            return None

    monkeypatch.setitem(
        sys.modules,
        "google.oauth2.credentials",
        types.SimpleNamespace(Credentials=_Creds),
    )
    monkeypatch.setitem(
        sys.modules,
        "google.auth.transport.requests",
        types.SimpleNamespace(Request=lambda: object()),
    )

    assert ysp.verify_youtube_credentials()["valid"] is True


def test_verify_requires_env(monkeypatch):
    from engine.publish import youtube_shorts_publisher as ysp

    _set_required_env(monkeypatch)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN")
    with pytest.raises(YouTubeShortsPublishError, match="YOUTUBE_REFRESH_TOKEN"):
        ysp.verify_youtube_credentials()


def test_invalid_grant_guide_is_actionable():
    from engine.publish.youtube_shorts_publisher import INVALID_GRANT_GUIDE

    assert "테스트" in INVALID_GRANT_GUIDE  # 7일 만료 원인
    assert "issue_youtube_token.py" in INVALID_GRANT_GUIDE  # 재발급 경로


# ── v1.3.0 OAuth 오류코드별 안내 (2026-08-29 오진 회고) ──────
# 배경: 에러가 unauthorized_client 인데 안내문이 invalid_grant 고정이라
#       "토큰 재발급"만 반복하게 만들었다. 실제 원인은 ID/SECRET 불일치.


def test_guide_for_unauthorized_client_points_to_client_mismatch():
    from engine.publish.youtube_shorts_publisher import oauth_error_guide

    guide = oauth_error_guide("('unauthorized_client: Unauthorized', {})")
    assert "unauthorized_client" in guide
    assert "CLIENT_ID/CLIENT_SECRET" in guide
    assert "한 세트" in guide


def test_guide_for_invalid_grant_points_to_token():
    from engine.publish.youtube_shorts_publisher import oauth_error_guide

    guide = oauth_error_guide("invalid_grant: Bad Request")
    assert "invalid_grant" in guide
    assert "만료" in guide


def test_guide_for_invalid_client():
    from engine.publish.youtube_shorts_publisher import oauth_error_guide

    guide = oauth_error_guide("invalid_client")
    assert "CLIENT_ID 또는 CLIENT_SECRET" in guide


def test_guide_falls_back_for_unknown_code():
    from engine.publish.youtube_shorts_publisher import oauth_error_guide

    guide = oauth_error_guide("something_unexpected")
    assert "같은 클라이언트 한 세트" in guide


def test_client_id_fingerprint_masks_value(monkeypatch):
    from engine.publish.youtube_shorts_publisher import client_id_fingerprint

    monkeypatch.setenv(
        "YOUTUBE_CLIENT_ID", "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
    )
    fp = client_id_fingerprint()
    assert fp.startswith("123456789012-")
    assert "abcdefghijklmnop" not in fp  # 전체 값은 노출하지 않는다


def test_client_id_fingerprint_when_unset(monkeypatch):
    from engine.publish.youtube_shorts_publisher import client_id_fingerprint

    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    assert client_id_fingerprint() == "(미설정)"
