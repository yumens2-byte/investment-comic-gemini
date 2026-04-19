"""
X Video Publisher — Twitter/X chunked video upload.

Purpose:
  After master approval, publish the 24s video to X (@tiger18272 or ICG account).

X Video Upload Requirements:
  - Must use chunked upload API (INIT → APPEND × N → FINALIZE → status poll)
  - Video size: max 512 MB
  - Video length: max 2:20 (140 seconds)
  - Format: MP4 with H.264 and AAC audio
  - Our 24s 1080x1920 mp4 is well within limits

API Flow:
  1. POST media/upload INIT    → media_id
  2. POST media/upload APPEND  × N (5MB chunks)
  3. POST media/upload FINALIZE
  4. GET  media/upload STATUS  (poll until processing_info.state = succeeded)
  5. POST statuses/update with media_ids and caption

Requirements:
  X_API_KEY (env)
  X_API_SECRET (env)
  X_ACCESS_TOKEN (env)
  X_ACCESS_SECRET (env)
"""
import logging
import os
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE_MB = 512
MAX_DURATION_SEC = 140
MAX_CAPTION_LEN = 280  # X post limit
CHUNK_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


class XVideoPublishError(Exception):
    """Raised when X video publish fails."""


def publish_video_to_x(
    video_path: str,
    caption: str,
    episode_id: str,
    additional_media_tags: Optional[list] = None,
) -> dict:
    """
    Upload video to X via chunked upload API, then post status.

    Args:
        video_path              : Final mp4 file
        caption                 : X post text (≤280 chars)
        episode_id              : Unique episode identifier (for logging)
        additional_media_tags   : Optional user tags

    Returns:
        dict: tweet_id, media_id, published_at
    """
    if not Path(video_path).exists():
        raise XVideoPublishError(f"video_path not found: {video_path}")

    size_mb = Path(video_path).stat().st_size / 1024 / 1024
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise XVideoPublishError(
            f"Video size {size_mb:.1f}MB exceeds X limit {MAX_VIDEO_SIZE_MB}MB"
        )

    if len(caption) > MAX_CAPTION_LEN:
        logger.warning(
            f"[x_video_publisher] caption too long ({len(caption)}), truncating to {MAX_CAPTION_LEN}"
        )
        caption = caption[: MAX_CAPTION_LEN - 3] + "..."

    for key in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"):
        if not os.environ.get(key):
            raise XVideoPublishError(f"{key} env not set")

    logger.info(
        f"[x_video_publisher] v{VERSION} X video publish start: "
        f"episode={episode_id} size={size_mb:.1f}MB"
    )

    # TODO: actual chunked upload via tweepy v4
    # import tweepy
    # auth = tweepy.OAuth1UserHandler(
    #     os.environ["X_API_KEY"],
    #     os.environ["X_API_SECRET"],
    #     os.environ["X_ACCESS_TOKEN"],
    #     os.environ["X_ACCESS_SECRET"],
    # )
    # api_v1 = tweepy.API(auth)  # v1.1 API for media upload (chunked)
    #
    # # 1. INIT + APPEND + FINALIZE via media_upload(chunked=True)
    # media = api_v1.media_upload(
    #     filename=video_path,
    #     media_category="tweet_video",
    #     chunked=True,
    #     wait_for_async_finalize=True,
    # )
    # media_id = media.media_id
    #
    # # 2. Post tweet with media_id via v2 API
    # client = tweepy.Client(
    #     consumer_key=os.environ["X_API_KEY"],
    #     consumer_secret=os.environ["X_API_SECRET"],
    #     access_token=os.environ["X_ACCESS_TOKEN"],
    #     access_token_secret=os.environ["X_ACCESS_SECRET"],
    # )
    # response = client.create_tweet(text=caption, media_ids=[media_id])
    # tweet_id = response.data["id"]
    #
    # return {
    #     "tweet_id": tweet_id,
    #     "media_id": media_id,
    #     "published_at": time.time(),
    # }

    logger.info("[x_video_publisher] X video publish done (SKELETON — implement in V5)")
    return {
        "tweet_id": None,
        "media_id": None,
        "published_at": None,
        "status": "skeleton",
    }
