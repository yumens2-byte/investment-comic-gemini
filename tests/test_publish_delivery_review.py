"""Regression checks for episode identity and delivery disclaimers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from engine.publish import telegram_publisher as tg
from engine.publish import x_publisher as xp
from engine.publish.claim_guard import PREFIX
from engine.quality.contracts import QualityHold
from scripts import run_publish
from tests.test_publish_claim_review import legacy_run  # noqa: F401


def test_video_lookup_does_not_fall_back_to_another_episode():
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[]), SimpleNamespace(data=[
        {"episode_id": "ICG-2026-09-25-002", "video_path": "wrong.mp4"}
    ])]
    assert run_publish._load_video_asset_row(lambda _: query, "ICG-2026-09-25-001", "2026-09-25") == {}
    assert query.execute.call_count == 1


@pytest.mark.parametrize("caption", ["A" * 1500, "A" * 1500 + tg._DISCLAIMER_REQUIRED])
def test_long_telegram_caption_keeps_disclaimer(caption):
    bounded = tg._bounded_caption(caption)
    assert len(bounded) <= 1024
    assert tg._DISCLAIMER_REQUIRED in bounded


@pytest.mark.parametrize("count", range(1, 11))
def test_x_final_disclaimer_stays_with_final_slide(tmp_path, monkeypatch, count):
    paths = []
    for i in range(count):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (2, 2)).save(path)
        paths.append(path)
    api, client = MagicMock(), MagicMock()
    api.media_upload.return_value = SimpleNamespace(media_id=123)
    client.create_tweet.return_value = SimpleNamespace(data={"id": "456"})
    monkeypatch.setattr(xp, "_make_clients", lambda: (api, client))
    monkeypatch.setattr(xp.time, "sleep", lambda _: None)
    xp.publish_episode_x({"caption_x_final": xp.DISCLAIMER_REQUIRED}, paths, dry_run=False)
    assert client.create_tweet.call_args.kwargs["text"] == xp.DISCLAIMER_REQUIRED


def test_successful_video_only_retains_hold_and_blocks_repost(legacy_run, tmp_path):  # noqa: F811
    run, _, row, monkeypatch, planner, x_video, _ = legacy_run
    plan = SimpleNamespace(enabled=True, channels=("x",), video_path=tmp_path / "clip.mp4",
                           x_caption="clip", reason="enabled")
    monkeypatch.setattr(planner, "build_battle_video_plan", lambda **kwargs: plan)
    sender = MagicMock(return_value={"tweet_id": "posted"})
    monkeypatch.setattr(x_video, "publish_video_to_x", sender)
    run("x", True)
    assert row["error_message"].startswith(PREFIX)
    with pytest.raises(QualityHold):
        run("x", True)
    assert sender.call_count == 1


@pytest.mark.parametrize("channel", ["x", "telegram"])
def test_optional_video_missing_id_records_images_but_keeps_hold(legacy_run, tmp_path, channel):  # noqa: F811
    run, calls, row, monkeypatch, planner, x_video, tg_video = legacy_run
    plan = SimpleNamespace(enabled=True, channels=(channel,), video_path=tmp_path / "clip.mp4",
                           x_caption="clip", telegram_title="clip", hashtags=(),
                           telegram_teaser="clip", reason="enabled")
    monkeypatch.setattr(planner, "build_battle_video_plan", lambda **kwargs: plan)
    provider = x_video if channel == "x" else tg_video
    function = "publish_video_to_x" if channel == "x" else "publish_to_free_channel"
    sender = MagicMock(return_value={})
    monkeypatch.setattr(provider, function, sender)
    with pytest.raises(QualityHold, match="images published"):
        run(channel)
    assert calls["history"] == 1
    assert row["error_message"].startswith(PREFIX)
    with pytest.raises(QualityHold):
        run(channel)
    assert sender.call_count == 1
