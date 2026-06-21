from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from engine.publish.telegram_video_publisher import _send_video
from engine.publish.x_video_publisher import publish_video_to_x


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
