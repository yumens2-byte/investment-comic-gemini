"""
YouTube Shorts Publisher — Upload 24s vertical video as YouTube Shorts.

Purpose:
  After master approval, publish the 24s video to YouTube Shorts.

Shorts Requirements (auto-detected by YT):
  - Vertical 9:16 aspect ratio (our 1080x1920 ✓)
  - Duration ≤ 60s (our 24s ✓)
  - Title should include #Shorts hashtag for discoverability

Auth Strategy:
  OAuth 2.0 refresh token flow (non-interactive, suitable for GitHub Actions)

Requirements:
  YOUTUBE_CLIENT_ID       (env, from Google Cloud Console)
  YOUTUBE_CLIENT_SECRET   (env)
  YOUTUBE_REFRESH_TOKEN   (env, generated once via OAuth Playground)

API: videos.insert with resumable upload
"""
import logging
import os
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

MAX_TITLE_LEN = 100
MAX_DESCRIPTION_LEN = 5000


class YouTubeShortsPublishError(Exception):
    """Raised when YouTube Shorts publish fails."""


def publish_to_youtube_shorts(
    video_path: str,
    title: str,
    description: str,
    episode_id: str,
    tags: Optional[list] = None,
    category_id: str = "25",  # News & Politics (fits our financial trailer)
    privacy_status: str = "public",
) -> dict:
    """
    Upload video to YouTube Shorts via resumable upload.

    Args:
        video_path      : Final mp4
        title           : Video title (#Shorts tag appended if not present)
        description     : Video description
        episode_id      : Unique episode identifier
        tags            : Optional list of tags
        category_id     : YouTube category (25=News, 22=People, 24=Entertainment)
        privacy_status  : "public" | "unlisted" | "private"

    Returns:
        dict: youtube_video_id, youtube_url, published_at
    """
    if not Path(video_path).exists():
        raise YouTubeShortsPublishError(f"video_path not found: {video_path}")

    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not os.environ.get(key):
            raise YouTubeShortsPublishError(f"{key} env not set")

    # Ensure #Shorts tag in title for discoverability
    if "#Shorts" not in title and "#shorts" not in title:
        title = f"{title} #Shorts"
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 3] + "..."

    if len(description) > MAX_DESCRIPTION_LEN:
        description = description[: MAX_DESCRIPTION_LEN - 3] + "..."

    logger.info(
        f"[youtube_shorts_publisher] v{VERSION} upload start: "
        f"episode={episode_id} title={title[:50]}..."
    )

    # TODO: actual YouTube Data API v3 upload
    # from google.oauth2.credentials import Credentials
    # from googleapiclient.discovery import build
    # from googleapiclient.http import MediaFileUpload
    #
    # creds = Credentials(
    #     None,
    #     refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
    #     token_uri="https://oauth2.googleapis.com/token",
    #     client_id=os.environ["YOUTUBE_CLIENT_ID"],
    #     client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
    # )
    # youtube = build("youtube", "v3", credentials=creds)
    #
    # body = {
    #     "snippet": {
    #         "title": title,
    #         "description": description,
    #         "tags": tags or [],
    #         "categoryId": category_id,
    #     },
    #     "status": {
    #         "privacyStatus": privacy_status,
    #         "selfDeclaredMadeForKids": False,
    #     },
    # }
    #
    # media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    # request = youtube.videos().insert(
    #     part=",".join(body.keys()),
    #     body=body,
    #     media_body=media,
    # )
    # response = request.execute()
    # video_id = response["id"]
    #
    # return {
    #     "youtube_video_id": video_id,
    #     "youtube_url": f"https://www.youtube.com/shorts/{video_id}",
    #     "published_at": response["snippet"]["publishedAt"],
    # }

    logger.info("[youtube_shorts_publisher] upload done (SKELETON — implement in V5)")
    return {
        "youtube_video_id": None,
        "youtube_url": None,
        "published_at": None,
        "status": "skeleton",
    }
