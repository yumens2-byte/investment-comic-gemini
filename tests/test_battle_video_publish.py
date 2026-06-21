from pathlib import Path

from engine.publish.battle_video_publish import (
    BATTLE_VIDEO_EVENT_TYPES,
    build_battle_video_plan,
    build_battle_video_x_caption,
    extract_battle_video_path,
    is_battle_video_event,
)
from scripts.run_publish import MAJOR_EVENT_TYPES


def test_battle_video_event_set_is_narrower_than_major_events():
    assert is_battle_video_event("BATTLE") is True
    assert is_battle_video_event("battle_plus_form3") is True
    assert is_battle_video_event("SHOCK") is False
    assert is_battle_video_event("NORMAL") is False
    assert BATTLE_VIDEO_EVENT_TYPES.issubset(MAJOR_EVENT_TYPES)


def test_extract_battle_video_path_accepts_direct_and_nested_shapes():
    assert extract_battle_video_path({"battle_video_path": "output/videos/battle.mp4"}) == Path(
        "output/videos/battle.mp4"
    )
    assert extract_battle_video_path(
        {"battle_video_json": {"final_mp4_path": "output/videos/final.mp4"}}
    ) == Path("output/videos/final.mp4")
    assert extract_battle_video_path({"video_assets": {"video_uri": "output/videos/cut1.mp4"}}) == Path(
        "output/videos/cut1.mp4"
    )
    assert extract_battle_video_path({"battle_video_json": {}}) is None


def test_build_battle_video_x_caption_stays_within_x_limit():
    caption = build_battle_video_x_caption(
        {
            "caption_x_cover": "A" * 300,
            "hashtags": ["#ICG", "#미주투자"],
        }
    )

    assert len(caption) == 280
    assert caption.startswith("A")


def test_build_battle_video_plan_is_disabled_without_affecting_image_flow(tmp_path):
    plan = build_battle_video_plan(
        row={"battle_video_path": str(tmp_path / "missing.mp4")},
        event_type="BATTLE",
        script_dict={},
        channels=["telegram"],
    )

    assert plan.enabled is False
    assert plan.reason == "video_file_missing"


def test_build_battle_video_plan_ready_for_existing_video(tmp_path):
    video = tmp_path / "battle.mp4"
    video.write_bytes(b"fake mp4")

    plan = build_battle_video_plan(
        row={"battle_video_path": str(video), "episode_id": "ICG-2026-06-20-001"},
        event_type="BATTLE_PLUS",
        script_dict={"caption_x_cover": "cover", "caption_telegram": "teaser", "hashtags": ["#ICG"]},
        channels=["telegram", "x"],
    )

    assert plan.enabled is True
    assert plan.reason == "ready"
    assert plan.video_path == video
    assert plan.channels == ("telegram", "x")
    assert plan.x_caption == "cover\n\n🎬 전투씬 영상\n\n#ICG"
    assert plan.telegram_teaser == "teaser"
