"""
engine/publish/x_publisher.py
X(Twitter) 발행 — 커버 1트윗 + 스레드 reply 체인.

핵심 규칙 (doc 16b, doc 00 RULE 09/10):
  - SLEEP_BETWEEN_TWEETS = 10초 강제
  - 자동 발행 절대 금지 — publish_sns.yml + confirm=YES 게이트 경유
  - DisclaimerMissing: caption_x_final에 면책 고지 미포함 시 ValueError
  - 슬라이드 8장 매핑:
      T1: S1 + caption_x_cover (커버)
      T2: S2~S4 + caption_x_parts[0]
      T3: S5~S7 + caption_x_parts[1]
      T4: S8 Disclaimer + caption_x_final
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from engine.common.exceptions import DisclaimerMissing

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_TWEETS = 10  # 초 (doc 16b 고정값)
DISCLAIMER_REQUIRED = "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다"


def _make_clients():
    """tweepy OAuth1 + v2 클라이언트 생성."""
    import tweepy

    auth = tweepy.OAuth1UserHandler(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    api_v1 = tweepy.API(auth)
    client_v2 = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return api_v1, client_v2


def _chunk_slides(slides: list[Path]) -> list[list[Path]]:
    """
    슬라이드 8장 → 4개 청크로 분할.

    T1: [S1]           (커버)
    T2: [S2, S3, S4]
    T3: [S5, S6, S7]
    T4: [S8]           (disclaimer)

    슬라이드가 10장인 경우:
    T1: [S1]
    T2: [S2, S3, S4]
    T3: [S5, S6, S7]
    T4: [S8, S9]
    T5: [S10]         (disclaimer)
    """
    if len(slides) == 0:
        return []

    chunks: list[list[Path]] = []

    if len(slides) <= 8:
        # 8장 기본 구조
        chunks.append([slides[0]])             # T1: 커버
        if len(slides) > 1:
            chunks.append(slides[1:4])         # T2: S2-S4
        if len(slides) > 4:
            chunks.append(slides[4:7])         # T3: S5-S7
        if len(slides) > 7:
            chunks.append([slides[7]])         # T4: disclaimer
    else:
        # 9~10장
        chunks.append([slides[0]])             # T1: 커버
        chunks.append(slides[1:4])             # T2: S2-S4
        chunks.append(slides[4:7])             # T3: S5-S7
        chunks.append(slides[7:-1])            # T4: 중간
        chunks.append([slides[-1]])            # T5: disclaimer

    return [c for c in chunks if c]  # 빈 청크 제거


def _upload_media(api_v1, image_paths: list[Path]) -> list[str]:
    """이미지 파일들을 X에 업로드하고 media_id 목록 반환."""
    media_ids: list[str] = []
    for path in image_paths:
        if not path.exists():
            logger.warning("[x_publisher] 슬라이드 없음: %s", path)
            continue
        media = api_v1.media_upload(filename=str(path))
        media_ids.append(str(media.media_id))
        logger.debug("[x_publisher] 이미지 업로드: %s → %s", path.name, media.media_id)
    return media_ids


def _guard_disclaimer(caption_x_final: str) -> None:
    """
    발행 직전 면책 고지 검증.

    Raises:
        DisclaimerMissing: 면책 고지 문구 없을 때.
    """
    if DISCLAIMER_REQUIRED not in caption_x_final:
        raise DisclaimerMissing(location="caption_x_final")


def publish_episode_x(
    script_dict: dict,
    slides: list[Path],
    dry_run: bool = True,
) -> list[str]:
    """
    에피소드를 X에 발행.

    Args:
        script_dict: EpisodeScript.model_dump() 결과.
        slides: PIL 조립된 슬라이드 경로 목록 (S1.png ~ S8.png).
        dry_run: True이면 실제 발행 없이 로그만.

    Returns:
        트윗 ID 목록 [T1_id, T2_id, T3_id, T4_id].

    Raises:
        DisclaimerMissing: 면책 고지 누락 시.
    """
    caption_x_cover = script_dict.get("caption_x_cover", "")
    caption_x_parts = script_dict.get("caption_x_parts", ["", ""])
    caption_x_final = script_dict.get("caption_x_final", "")
    hashtags = " ".join(script_dict.get("hashtags", []))

    # 면책 고지 검증 (발행 전 필수)
    _guard_disclaimer(caption_x_final)

    chunks = _chunk_slides(slides)
    if not chunks:
        raise ValueError("슬라이드 없음 — 발행 불가")

    # 캡션 목록 조립
    captions = [
        f"{caption_x_cover}\n\n{hashtags}".strip(),
        caption_x_parts[0] if len(caption_x_parts) > 0 else "",
        caption_x_parts[1] if len(caption_x_parts) > 1 else "",
        f"{caption_x_final}",
    ]
    # 청크 수에 맞게 캡션 조정
    while len(captions) < len(chunks):
        captions.append("")

    if dry_run:
        logger.info("[x_publisher] DRY_RUN — 발행 시뮬레이션")
        tweet_ids = []
        for i, (chunk, caption) in enumerate(zip(chunks, captions), start=1):
            logger.info(
                "[x_publisher] T%d: 슬라이드 %d장, 캡션=%s...",
                i, len(chunk), caption[:40]
            )
            tweet_ids.append(f"DRY_RUN_T{i}")
        return tweet_ids

    # 실 발행
    api_v1, client_v2 = _make_clients()
    tweet_ids: list[str] = []
    reply_to: str | None = None

    for i, (chunk, caption) in enumerate(zip(chunks, captions), start=1):
        media_ids = _upload_media(api_v1, chunk)

        kwargs: dict = {"text": caption}
        if media_ids:
            kwargs["media_ids"] = media_ids
        if reply_to:
            kwargs["in_reply_to_tweet_id"] = reply_to

        resp = client_v2.create_tweet(**kwargs)
        tweet_id = str(resp.data["id"])
        tweet_ids.append(tweet_id)
        reply_to = tweet_id

        logger.info("[x_publisher] T%d 발행 완료: %s", i, tweet_id)

        # 트윗 간 슬립 (X 레이트리밋 대응)
        if i < len(chunks):
            logger.debug("[x_publisher] %ds 대기...", SLEEP_BETWEEN_TWEETS)
            time.sleep(SLEEP_BETWEEN_TWEETS)

    return tweet_ids
