"""
scripts/run_publish.py
SNS 발행 수동 게이트 (STEP 8).

사용법:
  python -m scripts.run_publish --episode ICG-2026-04-14-001 --channels telegram
  python -m scripts.run_publish --episode ICG-2026-04-14-001 --channels x,telegram
  python -m scripts.run_publish --date 2026-04-14 --channels telegram
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("icg.run_publish")


def _parse_date(episode_id: str) -> str:
    m = re.match(r"ICG-(\d{4}-\d{2}-\d{2})-\d{3}", episode_id)
    if not m:
        raise ValueError(f"잘못된 episode_id: {episode_id}")
    return m.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG SNS 발행 (STEP 8)")
    parser.add_argument("--episode", help="에피소드 ID")
    parser.add_argument("--date", help="날짜 (YYYY-MM-DD)")
    parser.add_argument("--channels", default="telegram", help="발행 채널 (telegram/x/all)")
    args = parser.parse_args()

    # episode / date 미입력 시 Supabase 최신 assembled 에피소드 자동 선택
    if not args.episode and not args.date:
        from engine.common.supabase_client import icg_table as _tbl

        for _status in ("assembled", "image_generated"):
            _rows = (
                _tbl("episode_assets")
                .select("episode_date, episode_no")
                .eq("status", _status)
                .order("episode_date", desc=True)
                .order("episode_no", desc=True)
                .limit(1)
                .execute()
            )
            if _rows.data:
                _r = _rows.data[0]
                _ep_date = str(_r["episode_date"])
                _ep_no = _r.get("episode_no") or 1
                args.episode = f"ICG-{_ep_date}-{_ep_no:03d}"
                logger.info("[run_publish] 자동 선택: %s (status=%s)", args.episode, _status)
                break
        if not args.episode:
            logger.error("실행 가능한 에피소드 없음 (assembled/image_generated 없음)")
            sys.exit(1)

    episode_date = args.date or _parse_date(args.episode)

    import os

    from engine.common.logger import StepLogger, get_run_id
    from engine.common.supabase_client import icg_table
    from engine.publish.history_writer import record_publish
    from engine.publish.telegram_publisher import publish_episode_telegram
    from engine.publish.x_publisher import publish_episode_x

    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"

    run_id = get_run_id(episode_date)
    output_dir = Path("output") / "episodes" / episode_date
    sl = StepLogger(run_id=run_id, episode_date=episode_date, output_dir=output_dir)

    # episode_assets 로드
    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not rows.data:
        sl.error("STEP_8", f"episode_assets 없음: {episode_date}")
        sys.exit(1)

    row = rows.data[0]
    event_type = row.get("event_type", "NORMAL")
    script_dict = row.get("script_json", {})
    episode_id = args.episode or f"ICG-{episode_date}-001"

    # ── 중복 발행 방어 (Layer 1) ─────────────────────────────────────────
    # 1) 이미 published 상태면 차단 (FORCE_REPUBLISH=true 환경변수로만 우회)
    current_status = row.get("status", "")
    force_republish = os.environ.get("FORCE_REPUBLISH", "false").lower() == "true"
    if current_status == "published" and not force_republish:
        sl.error(
            "STEP_8",
            f"🛑 중복 발행 차단 — episode={episode_id} status=published 이미 발행됨. "
            f"재발행이 필요하면 FORCE_REPUBLISH=true 환경변수 설정 후 재실행.",
        )
        logger.error("❌ 이미 published 상태. 중복 발행 차단.")
        sys.exit(1)

    # 2) published_comics 테이블 이중 체크 (asset_writer 실패 시 대비)
    try:
        ep_no = int(episode_id.split("-")[-1])
        dup_rows = (
            icg_table("published_comics")
            .select("id, tweet_id, created_at")
            .eq("publish_date", episode_date)
            .eq("episode_no", ep_no)
            .eq("comic_type", event_type)
            .limit(1)
            .execute()
        )
        if dup_rows.data and not force_republish:
            existing = dup_rows.data[0]
            sl.error(
                "STEP_8",
                f"🛑 published_comics 중복 차단 — episode={episode_id} "
                f"이미 발행 이력 존재 (id={existing.get('id')}, "
                f"tweet_id={existing.get('tweet_id')}, "
                f"created_at={existing.get('created_at')}).",
            )
            logger.error("❌ published_comics에 이미 기록됨. 중복 발행 차단.")
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as exc:
        sl.warning("STEP_8", f"published_comics 중복 체크 실패 (진행): {exc}")

    # 슬라이드 경로 복원
    slides_json = row.get("slides_json", [])
    slides = [Path(s["path"]) for s in slides_json if isinstance(s, dict) and s.get("path")]

    if not slides:
        sl.error("STEP_8", "슬라이드 없음 — run_resume 먼저 실행")
        sys.exit(1)

    channels = args.channels.lower().split(",")
    tweet_ids: list[str] = []
    telegram_sent = False

    ts_total = time.monotonic()
    sl.info("STEP_8", f"발행 시작 channels={channels} dry_run={dry_run}")

    # X 발행
    if "x" in channels or "all" in channels:
        ts = sl.step_start("STEP_8_X", "X 발행")
        try:
            tweet_ids = publish_episode_x(script_dict, slides, dry_run=dry_run)
            sl.step_done("STEP_8_X", ts, f"트윗 {len(tweet_ids)}개")
        except Exception as exc:
            sl.step_fail("STEP_8_X", ts, exc)

    # Telegram 발행
    if "telegram" in channels or "all" in channels:
        import os

        tg_channels = []
        free_id = os.environ.get("TELEGRAM_FREE_CHANNEL_ID", "")
        if free_id:
            tg_channels.append(free_id)

        ts = sl.step_start("STEP_8_TG", "Telegram 발행")
        try:
            results = publish_episode_telegram(script_dict, slides, tg_channels, dry_run=dry_run)
            telegram_sent = any(results.values())
            sl.step_done("STEP_8_TG", ts, f"결과: {results}")
        except Exception as exc:
            sl.step_fail("STEP_8_TG", ts, exc)

    # 발행 이력 기록
    runtime = round(time.monotonic() - ts_total, 1)
    try:
        record_publish(
            episode_date=episode_date,
            episode_id=episode_id,
            event_type=event_type,
            tweet_ids=tweet_ids,
            telegram_sent=telegram_sent,
            slide_count=len(slides),
            gemini_cost_usd=float(row.get("gemini_cost_usd", 0) or 0),
            claude_cost_usd=float(row.get("claude_cost_usd", 0) or 0),
            runtime_sec=runtime,
        )
    except Exception as exc:
        sl.warning("STEP_8", f"이력 기록 실패 (영향 없음): {exc}")

    sl.info("STEP_8", f"발행 완료 runtime={runtime}s")
    logger.info("✅ 발행 완료 episode_id=%s", episode_id)


if __name__ == "__main__":
    main()
