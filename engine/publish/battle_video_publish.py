"""Optional battle-scene video add-on publishing helpers.

This module is intentionally isolated from the existing image/PIL comic publishing
flow.  It only plans and executes an additional mp4 post for battle events when a
video asset is present; callers should continue to publish the image slides first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

BATTLE_VIDEO_EVENT_TYPES = frozenset({
    "BATTLE",
    "BATTLE_PLUS",
    "BATTLE_PLUS_FORM2",
    "BATTLE_PLUS_FORM3",
})

X_MAX_CAPTION_LEN = 280


@dataclass(frozen=True)
class BattleVideoPublishPlan:
    """Execution plan for the optional battle-video add-on."""

    enabled: bool
    reason: str
    video_path: Path | None = None
    channels: tuple[str, ...] = ()
    x_caption: str = ""
    telegram_title: str = ""
    telegram_teaser: str = ""
    hashtags: tuple[str, ...] = ()


def is_battle_video_event(event_type: str) -> bool:
    """Return True when an episode type is eligible for battle-scene video upload."""
    return (event_type or "").upper() in BATTLE_VIDEO_EVENT_TYPES


def extract_battle_video_path(row: dict[str, Any]) -> Path | None:
    """Extract an optional battle-scene mp4 path from evolving asset shapes.

    Supported shapes are deliberately explicit and backwards-compatible:
    - top-level: battle_video_path, final_video_path, video_path
    - nested JSON: battle_video_json/video_json/video_assets with path,
      video_path, final_mp4_path, final_video_path, video_uri, or uri
    """
    direct_keys = ("battle_video_path", "final_video_path", "video_path")
    for key in direct_keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value)

    json_keys = ("battle_video_json", "video_json", "video_assets")
    path_keys = ("path", "video_path", "final_mp4_path", "final_video_path", "video_uri", "uri")
    for key in json_keys:
        value = row.get(key)
        if not isinstance(value, dict):
            continue
        for path_key in path_keys:
            path_value = value.get(path_key)
            if isinstance(path_value, str) and path_value.strip():
                return Path(path_value)

    return None


def build_battle_video_x_caption(script_dict: dict[str, Any]) -> str:
    """Build an X-safe caption for the battle-scene video add-on."""
    cover = str(script_dict.get("caption_x_cover") or "").strip()
    hashtags = " ".join(script_dict.get("hashtags", []) or [])
    caption = "\n\n".join(part for part in (cover, "🎬 전투씬 영상", hashtags) if part)
    return caption[:X_MAX_CAPTION_LEN]


def build_battle_video_plan(
    *,
    row: dict[str, Any],
    event_type: str,
    script_dict: dict[str, Any],
    channels: list[str],
) -> BattleVideoPublishPlan:
    """Plan optional battle-video publication without touching image slide flow."""
    if not is_battle_video_event(event_type):
        return BattleVideoPublishPlan(enabled=False, reason="not_battle_event")

    video_path = extract_battle_video_path(row)
    if not video_path:
        return BattleVideoPublishPlan(enabled=False, reason="video_asset_missing")

    if not video_path.exists():
        return BattleVideoPublishPlan(
            enabled=False,
            reason="video_file_missing",
            video_path=video_path,
        )

    normalized_channels = tuple(c for c in channels if c in {"telegram", "x", "all"})
    if not normalized_channels:
        return BattleVideoPublishPlan(
            enabled=False,
            reason="unsupported_channels",
            video_path=video_path,
        )

    return BattleVideoPublishPlan(
        enabled=True,
        reason="ready",
        video_path=video_path,
        channels=normalized_channels,
        x_caption=build_battle_video_x_caption(script_dict),
        telegram_title=str(script_dict.get("title") or row.get("episode_id") or "전투씬 영상"),
        telegram_teaser=str(
            script_dict.get("caption_telegram")
            or script_dict.get("caption_x_cover")
            or "전투씬 영상"
        ),
        hashtags=tuple(script_dict.get("hashtags", []) or []),
    )
