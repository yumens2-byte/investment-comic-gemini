from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from engine.publish.telegram_video_publisher import _send_video
from engine.publish.x_video_publisher import (
    WEEKLY_HASHTAGS,
    WEEKLY_CAPTION_SAFE_LEN,
    build_weekly_x_caption,
    publish_video_to_x,
)


def test_telegram_send_video_uses_bot_api(monkeypatch, tmp_path):
    video = tmp_path / "battle.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")

    response = MagicMock()
    response.json.return_value = {"result": {"message_id": 123, "date": 456}}
    post = MagicMock(return_value=response)
    monkeypatch.setattr("engine.publish.telegram_video_publisher.requests.post", post)

    result = _send_video(str(video), "@channel", "caption", "EP1", "free")

    assert result["status"] == "published"
    assert result["message_id"] == 123
    post.assert_called_once()
    assert post.call_args.kwargs["data"]["supports_streaming"] == "true"


def test_x_video_publish_uses_chunked_upload(monkeypatch, tmp_path):
    video = tmp_path / "battle.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("X_API_KEY", "key")
    monkeypatch.setenv("X_API_SECRET", "secret")
    monkeypatch.setenv("X_ACCESS_TOKEN", "token")
    monkeypatch.setenv("X_ACCESS_TOKEN_SECRET", "access-secret")

    api = MagicMock()
    api.media_upload.return_value = SimpleNamespace(media_id="m123")
    client = MagicMock()
    client.create_tweet.return_value = SimpleNamespace(data={"id": "t123"})

    tweepy = SimpleNamespace(
        OAuth1UserHandler=MagicMock(return_value="auth"),
        API=MagicMock(return_value=api),
        Client=MagicMock(return_value=client),
    )
    monkeypatch.setitem(__import__("sys").modules, "tweepy", tweepy)

    result = publish_video_to_x(str(video), "caption", "EP1")

    assert result["status"] == "published"
    assert result["tweet_id"] == "t123"
    api.media_upload.assert_called_once_with(
        filename=str(video),
        media_category="tweet_video",
        chunked=True,
        wait_for_async_finalize=True,
    )
    client.create_tweet.assert_called_once_with(text="caption", media_ids=["m123"])


def test_x_video_publish_requires_credentials(monkeypatch, tmp_path):
    video = tmp_path / "battle.mp4"
    video.write_bytes(b"video")
    monkeypatch.delenv("X_API_KEY", raising=False)

    with pytest.raises(Exception, match="X_API_KEY"):
        publish_video_to_x(str(video), "caption", "EP1")


def test_weekly_x_caption_contains_story_summary_and_hashtags():
    caption = build_weekly_x_caption(
        "금리 충격에서 기술주 반등까지",
        ["주초 금리 경계감이 시장을 눌렀다", "주후반 기술주가 반등했다"],
    )

    assert "주초 금리 경계감이 시장을 눌렀다 → 주후반 기술주가 반등했다" in caption
    assert "투자 권유가 아닙니다" in caption
    assert all(tag in caption for tag in WEEKLY_HASHTAGS)
    assert len(caption) <= WEEKLY_CAPTION_SAFE_LEN


def test_weekly_x_caption_truncates_summary_but_preserves_hashtags():
    caption = build_weekly_x_caption("긴 주간 이야기", ["시장 변동 " * 100])

    assert len(caption) <= WEEKLY_CAPTION_SAFE_LEN
    assert "…" in caption
    assert caption.endswith(" ".join(WEEKLY_HASHTAGS))
