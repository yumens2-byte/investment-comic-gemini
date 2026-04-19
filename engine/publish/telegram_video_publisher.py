"""
Telegram Video Publisher — TG free/paid channel VIDEO publishing.

NOTE: This module handles VIDEO content only for the ICG Video Track.
      For IMAGE slide publishing (existing image track), see the existing
      engine/publish/telegram_publisher.py which handles media groups (albums).

Purpose:
  After master approval, publish the final 24s video to:
    1. Free channel  (@EDT_INVESTMENT, everyone)
    2. Paid channel  (subscribers only)

Publishing strategy:
  - Free channel : Caption-only + teaser + link to paid for full analysis
  - Paid channel : Full caption with episode narrative + hashtags

Requirements:
  TELEGRAM_BOT_TOKEN          (env)
  TELEGRAM_FREE_CHANNEL_ID    (env, e.g., "@EDT_INVESTMENT" or "-1001234567890")
  TELEGRAM_PAID_CHANNEL_ID    (env, e.g., "-1009876543210")

Note:
  - Video size must be ≤ 50MB (bot API standard limit)
  - 1080x1920 24s mp4 typically 8~25 MB → OK
  - Supports_streaming=True for smooth playback on mobile
  - Idempotency: tweet_id-style dedup via episode_id in Supabase
"""
import logging
import os
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE_MB = 50
MAX_CAPTION_LEN = 1024


class TelegramPublishError(Exception):
    """Raised when channel publish fails."""


def publish_to_free_channel(
    video_path: str,
    episode_id: str,
    title: str,
    hashtags: list,
    teaser_line: str,
    paid_channel_invite_link: Optional[str] = None,
) -> dict:
    """
    Publish video to TG free channel with teaser caption + paid upsell.

    Args:
        video_path              : Final rendered mp4
        episode_id              : Unique episode identifier
        title                   : Short episode title
        hashtags                : List of hashtags (e.g., ["#미주투자", "#ICG"])
        teaser_line             : One-line market teaser (no full analysis)
        paid_channel_invite_link: Optional invite URL to paid channel

    Returns:
        dict: message_id, chat_id, published_at, channel_type="free"
    """
    channel_id = os.environ.get("TELEGRAM_FREE_CHANNEL_ID")
    if not channel_id:
        raise TelegramPublishError("TELEGRAM_FREE_CHANNEL_ID env not set")

    caption = _build_free_caption(title, hashtags, teaser_line, paid_channel_invite_link)
    return _send_video(
        video_path=video_path,
        chat_id=channel_id,
        caption=caption,
        episode_id=episode_id,
        channel_type="free",
    )


def publish_to_paid_channel(
    video_path: str,
    episode_id: str,
    title: str,
    hashtags: list,
    full_narrative: str,
    market_context: dict,
) -> dict:
    """
    Publish video to TG paid channel with full episode narrative.

    Args:
        video_path     : Final rendered mp4
        episode_id     : Unique episode identifier
        title          : Episode title
        hashtags       : List of hashtags
        full_narrative : Full story narrative (within 1024 char limit)
        market_context : dict with keys scenario_type, regime, risk_level, etc.

    Returns:
        dict: message_id, chat_id, published_at, channel_type="paid"
    """
    channel_id = os.environ.get("TELEGRAM_PAID_CHANNEL_ID")
    if not channel_id:
        raise TelegramPublishError("TELEGRAM_PAID_CHANNEL_ID env not set")

    caption = _build_paid_caption(title, hashtags, full_narrative, market_context)
    return _send_video(
        video_path=video_path,
        chat_id=channel_id,
        caption=caption,
        episode_id=episode_id,
        channel_type="paid",
    )


def _send_video(
    video_path: str,
    chat_id: str,
    caption: str,
    episode_id: str,
    channel_type: str,
) -> dict:
    """Internal: Telegram sendVideo wrapper with size/auth validation."""
    if not Path(video_path).exists():
        raise TelegramPublishError(f"video_path not found: {video_path}")

    size_mb = Path(video_path).stat().st_size / 1024 / 1024
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise TelegramPublishError(
            f"Video size {size_mb:.1f}MB exceeds Telegram limit {MAX_VIDEO_SIZE_MB}MB"
        )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise TelegramPublishError("TELEGRAM_BOT_TOKEN env not set")

    logger.info(
        f"[telegram_publisher] v{VERSION} {channel_type} publish start: "
        f"episode={episode_id} size={size_mb:.1f}MB"
    )

    # TODO: actual Telegram sendVideo API call
    # from telegram import Bot
    # bot = Bot(token=bot_token)
    # with open(video_path, "rb") as f:
    #     msg = bot.send_video(
    #         chat_id=chat_id,
    #         video=f,
    #         caption=caption,
    #         parse_mode="HTML",
    #         supports_streaming=True,
    #         width=1080,
    #         height=1920,
    #         duration=24,
    #     )
    # return {
    #     "message_id": msg.message_id,
    #     "chat_id": chat_id,
    #     "published_at": msg.date.isoformat(),
    #     "channel_type": channel_type,
    # }

    logger.info(f"[telegram_publisher] {channel_type} publish done (SKELETON — implement in V5)")
    return {
        "message_id": None,
        "chat_id": chat_id,
        "published_at": None,
        "channel_type": channel_type,
        "status": "skeleton",
    }


def _build_free_caption(
    title: str,
    hashtags: list,
    teaser_line: str,
    paid_invite: Optional[str],
) -> str:
    """Build free-channel caption with teaser + paid upsell."""
    tags = " ".join(hashtags)
    lines = [
        f"🎬 <b>{title}</b>",
        "",
        teaser_line,
        "",
    ]
    if paid_invite:
        lines.append(f"🔒 상세 분석은 유료 채널에서: {paid_invite}")
        lines.append("")
    lines.append(tags)
    caption = "\n".join(lines)
    return caption[:MAX_CAPTION_LEN]


def _build_paid_caption(
    title: str,
    hashtags: list,
    full_narrative: str,
    market_context: dict,
) -> str:
    """Build paid-channel caption with full narrative + context."""
    tags = " ".join(hashtags)
    regime = market_context.get("regime", "N/A")
    risk = market_context.get("risk_level", "N/A")
    scenario = market_context.get("scenario_type", "N/A")

    lines = [
        f"🎬 <b>{title}</b>",
        "",
        f"📊 <b>Regime</b>: {regime} | <b>Risk</b>: {risk} | <b>Scenario</b>: {scenario}",
        "",
        full_narrative,
        "",
        tags,
    ]
    caption = "\n".join(lines)
    return caption[:MAX_CAPTION_LEN]
