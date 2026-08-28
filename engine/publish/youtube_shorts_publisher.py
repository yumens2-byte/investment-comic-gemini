"""
YouTube Shorts Publisher — Upload vertical video as YouTube Shorts.

Purpose:
  After master approval, publish the final vertical video to YouTube Shorts.
  (Daily Battle Shorts track — video generated only on major battle events.)

Shorts Requirements (auto-detected by YT):
  - Vertical 9:16 aspect ratio (our 1080x1920 OK)
  - Duration <= 60s (our ~30s OK)
  - Title should include #Shorts hashtag for discoverability

Auth Strategy:
  OAuth 2.0 refresh token flow (non-interactive, suitable for GitHub Actions)

Requirements:
  YOUTUBE_CLIENT_ID       (env, from Google Cloud Console)
  YOUTUBE_CLIENT_SECRET   (env)
  YOUTUBE_REFRESH_TOKEN   (env, generated once via scripts/issue_youtube_token.py)

API: videos.insert with resumable upload
Quota: videos.insert = 1600 quota units per call (daily default quota 10,000).
       Logged per upload in the same per-generation cost-log style as
       engine/image/gemini_client.py and engine/video/veo_client.py.

DRY_RUN policy (공통 지침 준수):
  os.environ.get("DRY_RUN", "true").lower() == "true"  -> no actual upload.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

VERSION = "1.1.0"
logger = logging.getLogger(__name__)

MAX_TITLE_LEN = 100
MAX_DESCRIPTION_LEN = 5000

# YouTube Data API v3 quota cost for videos.insert (fixed by Google).
UPLOAD_QUOTA_UNITS = 1600
TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB resumable chunks
RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_CHUNK_RETRY = 3

REQUIRED_ENV_KEYS = (
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
)


class YouTubeShortsPublishError(Exception):
    """Raised when YouTube Shorts publish fails."""


def _is_dry_run(dry_run: Optional[bool] = None) -> bool:
    """DRY_RUN 판정 — 공통 지침서 통일 규약과 동일한 판정식."""
    if dry_run is not None:
        return dry_run
    return os.environ.get("DRY_RUN", "true").lower() == "true"


def build_shorts_metadata(
    title: str,
    description: str,
    tags: Optional[list] = None,
    category_id: str = "25",
    privacy_status: str = "public",
) -> dict:
    """
    videos.insert body 조립 (순수 함수 — 단위 테스트 대상).

    - #Shorts 태그가 제목에 없으면 부착.
    - 제목/설명 길이 초과 시 절단.
    """
    if "#Shorts" not in title and "#shorts" not in title:
        title = f"{title} #Shorts"
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 3] + "..."
    if len(description) > MAX_DESCRIPTION_LEN:
        description = description[: MAX_DESCRIPTION_LEN - 3] + "..."

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }


def _validate_env() -> None:
    for key in REQUIRED_ENV_KEYS:
        if not os.environ.get(key):
            raise YouTubeShortsPublishError(f"{key} env not set")


def _build_youtube_service():
    """google-api-python-client 지연 import — 미설치 환경에서도 모듈 import 가능."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - 의존성 미설치 환경 안내
        raise YouTubeShortsPublishError(
            "google-api-python-client / google-auth 미설치. "
            "requirements.txt의 google-api-python-client, google-auth 설치 필요."
        ) from exc

    creds = Credentials(
        None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _execute_resumable_upload(request) -> dict:
    """resumable next_chunk 루프. 5xx는 청크 단위 재시도 (세션 유지 — 중복 업로드 없음)."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError as exc:  # pragma: no cover
        raise YouTubeShortsPublishError("googleapiclient 미설치") from exc

    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                logger.info(
                    "[youtube_shorts_publisher] upload progress: %d%%",
                    int(status.progress() * 100),
                )
        except HttpError as exc:
            if exc.resp.status in RETRIABLE_STATUS and retry < MAX_CHUNK_RETRY:
                retry += 1
                wait_sec = 2**retry
                logger.warning(
                    "[youtube_shorts_publisher] HTTP %s — chunk retry %d/%d (%ds 대기)",
                    exc.resp.status,
                    retry,
                    MAX_CHUNK_RETRY,
                    wait_sec,
                )
                time.sleep(wait_sec)
                continue
            raise YouTubeShortsPublishError(f"upload failed: HTTP {exc.resp.status}") from exc
    return response


def publish_to_youtube_shorts(
    video_path: str,
    title: str,
    description: str,
    episode_id: str,
    tags: Optional[list] = None,
    category_id: str = "25",  # News & Politics (fits our financial content)
    privacy_status: str = "public",
    dry_run: Optional[bool] = None,
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
        dry_run         : None이면 env DRY_RUN 판정 (공통 규약)

    Returns:
        dict: youtube_video_id, youtube_url, published_at, status, quota_units
    """
    logger.info(
        f"[youtube_shorts_publisher] v{VERSION} upload start: "
        f"episode={episode_id} privacy={privacy_status}"
    )

    if not Path(video_path).exists():
        raise YouTubeShortsPublishError(f"video_path not found: {video_path}")

    _validate_env()

    body = build_shorts_metadata(
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy_status=privacy_status,
    )

    if _is_dry_run(dry_run):
        logger.info(
            "[youtube_shorts_publisher] DRY_RUN — 업로드 스킵 "
            f"(title={body['snippet']['title'][:50]}...)"
        )
        return {
            "youtube_video_id": None,
            "youtube_url": None,
            "published_at": None,
            "status": "dry_run",
            "quota_units": 0,
        }

    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover
        raise YouTubeShortsPublishError("googleapiclient 미설치") from exc

    youtube = _build_youtube_service()
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        chunksize=UPLOAD_CHUNK_SIZE,
        resumable=True,
    )
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    start = time.monotonic()
    response = _execute_resumable_upload(request)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    video_id = response["id"]
    published_at = response.get("snippet", {}).get("publishedAt")

    # 생성(업로드)당 비용 로그 — 기존 gemini/veo 클라이언트와 동일 스타일
    logger.info(
        f"[youtube_shorts_publisher] upload done: video_id={video_id} "
        f"elapsed={elapsed_ms}ms cost={UPLOAD_QUOTA_UNITS}quota_units"
    )

    return {
        "youtube_video_id": video_id,
        "youtube_url": f"https://www.youtube.com/shorts/{video_id}",
        "published_at": published_at,
        "status": "published",
        "quota_units": UPLOAD_QUOTA_UNITS,
    }
