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
import os
import sys
import time
from pathlib import Path


def _ensure_repo_root_on_path() -> None:
    """Allow this script to import project packages when run as a file."""
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)


_ensure_repo_root_on_path()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("icg.run_publish")


MAJOR_EVENT_TYPES = frozenset(
    {
        "BATTLE",
        "SHOCK",
        "AFTERMATH",
        "EMERGENCE",
        "SEASON_FINALE",
        "BATTLE_PLUS",
        "BATTLE_PLUS_FORM2",
        "BATTLE_PLUS_FORM3",
    }
)


def is_major_event(event_type: str) -> bool:
    return (event_type or "").upper() in MAJOR_EVENT_TYPES


def validate_major_event_types() -> tuple[set[str], set[str]]:
    """Return (unknown_major_types, missing_recommended_major_types)."""
    supported_types: set[str] = {
        "BATTLE",
        "SHOCK",
        "AFTERMATH",
        "INTEL",
        "NORMAL",
        "FLASHBACK",
        "TACTICAL",
        "BATTLE_PLUS",
        "BATTLE_PLUS_FORM2",
        "BATTLE_PLUS_FORM3",
        "STALEMATE",
        "CONFLICT",
        "EMERGENCE",
        "SEASON_FINALE",
    }
    recommended_major_types = {
        "BATTLE",
        "SHOCK",
        "AFTERMATH",
        "BATTLE_PLUS",
        "BATTLE_PLUS_FORM2",
        "BATTLE_PLUS_FORM3",
        "EMERGENCE",
        "SEASON_FINALE",
    }
    unknown = MAJOR_EVENT_TYPES - supported_types
    missing = recommended_major_types - MAJOR_EVENT_TYPES
    return unknown, missing


def _parse_date(episode_id: str) -> str:
    from scripts.resolve_episode import _parse_episode_id

    return _parse_episode_id(episode_id)[0]


def _channel_requested(channels: list[str], channel: str) -> bool:
    return channel in channels or "all" in channels


def _merge_video_asset_row(row: dict, video_row: dict) -> dict:
    """Return episode row enriched with optional icg.video_assets path fields."""
    if not video_row:
        return row

    merged = dict(row)
    video_json = dict(merged.get("video_assets") or {})
    for key in (
        "battle_video_path",
        "final_video_path",
        "video_path",
        "cut1_video_uri",
        "final_mp4_path",
        "video_uri",
    ):
        value = video_row.get(key)
        if value and not merged.get(key):
            merged[key] = value
        if value:
            video_json.setdefault(key, value)

    if video_json:
        merged["video_assets"] = video_json
    return merged


def _load_video_asset_row(icg_table, episode_id: str, episode_date: str) -> dict:
    """Best-effort lookup of a separately generated video asset for this episode."""
    try:
        rows = (
            icg_table("video_assets")
            .select("*")
            .eq("episode_id", episode_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            return rows.data[0]
    except Exception as exc:  # noqa: BLE001 - optional video add-on must not block images
        logger.info("[run_publish] video_assets episode_id lookup skipped: %s", exc)

    # A date can contain several episodes. Never attach another episode's video
    # when the exact episode lookup is absent or failed.
    return {}


def _merge_local_video_path(row: dict, episode_id: str) -> dict:
    """Attach a downloaded local mp4 when DB metadata has no explicit video path."""
    if any(
        row.get(key)
        for key in ("battle_video_path", "final_video_path", "video_path", "cut1_video_uri")
    ):
        return row

    candidates = [
        Path("output") / "videos" / episode_id / "final.mp4",
        Path("output") / "videos" / episode_id / "cut1.mp4",
    ]
    candidates.extend(sorted((Path("output") / "videos" / episode_id).glob("*.mp4")))
    for candidate in candidates:
        if candidate.exists():
            merged = dict(row)
            merged["video_path"] = str(candidate)
            video_json = dict(merged.get("video_assets") or {})
            video_json.setdefault("video_path", str(candidate))
            merged["video_assets"] = video_json
            return merged
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG SNS 발행 (STEP 8)")
    parser.add_argument("--episode", help="에피소드 ID")
    parser.add_argument("--date", help="날짜 (YYYY-MM-DD)")
    parser.add_argument("--channels", default="telegram", help="발행 채널 (telegram/x/all)")
    parser.add_argument("--dry-run", action="store_true", help="읽기 전용 발행 준비 점검")
    parser.add_argument("--preflight-only", action="store_true", help="전송 없이 발행 준비 점검")
    parser.add_argument("--report", default="output/publish-preflight.json")
    parser.add_argument(
        "--video-only",
        action="store_true",
        help="이미지 재발행 없이 연결된 전투씬 영상 add-on만 발행",
    )
    args = parser.parse_args()
    from engine.quality.publish_guard import normalize_channels, require_publication_id

    args.channels = ",".join(normalize_channels(args.channels))
    if args.date:
        from datetime import date

        if date.fromisoformat(args.date).isoformat() != args.date:
            raise ValueError("Date must use YYYY-MM-DD")
    if args.episode:
        parsed_date = _parse_date(args.episode)
        if args.date and args.date != parsed_date:
            raise ValueError("episode/date mismatch")
    from scripts.publish_preflight import inspect_publish, parse_dry_run

    configured_dry_run = parse_dry_run(os.environ.get("DRY_RUN", "true"))
    dry_run = args.dry_run or configured_dry_run
    if dry_run or args.preflight_only:
        from scripts.market_preflight import emit_report

        report = inspect_publish(args.episode, args.date, args.channels, dry_run=dry_run,
                                 video_only=args.video_only)
        emit_report(report, Path(args.report))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
                handle.write(f"allowed={'true' if report['allowed'] else 'false'}\n")
        if not dry_run and report['status'] == 'incomplete':
            raise SystemExit(1)
        return

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

    from engine.common.logger import StepLogger, get_run_id
    from engine.common.supabase_client import icg_table
    from engine.publish.battle_video_publish import build_battle_video_plan
    from engine.publish.history_writer import record_publish
    from engine.publish.telegram_publisher import publish_episode_telegram
    from engine.publish.telegram_video_publisher import publish_to_free_channel
    from engine.publish.x_publisher import publish_episode_x
    from engine.publish.x_video_publisher import publish_video_to_x

    run_id = get_run_id(episode_date)
    output_dir = Path("output") / "episodes" / episode_date
    sl = StepLogger(run_id=run_id, episode_date=episode_date, output_dir=output_dir)

    # Resolve the requested episode number as well as its trading date.
    if args.episode and _parse_date(args.episode) != episode_date:
        raise ValueError("episode/date mismatch")
    episode_no = int(args.episode.split("-")[-1]) if args.episode else 1
    # episode_assets 로드
    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .eq("episode_no", episode_no)
        .order("created_at", desc=True)
        .limit(2)
        .execute()
    )
    if not rows.data:
        sl.error("STEP_8", f"episode_assets 없음: {episode_date}")
        sys.exit(1)
    if not isinstance(rows.data, list) or len(rows.data) != 1:
        raise ValueError("ambiguous episode identity")

    row = rows.data[0]
    if row.get("status") not in {"assembled", "image_generated", "published"}:
        raise ValueError("episode is not ready for publication")
    episode_id = args.episode or f"ICG-{episode_date}-001"
    row = _merge_video_asset_row(row, _load_video_asset_row(icg_table, episode_id, episode_date))
    row = _merge_local_video_path(row, episode_id)
    event_type = row.get("event_type", "NORMAL")
    script_dict = row.get("script_json", {})

    from engine.quality.publish_guard import guard_legacy_track

    guard_legacy_track(script_dict, row)
    from engine.publish.claim_guard import (
        claim_publication,
        finish_publication,
        require_no_publication_hold,
    )

    require_no_publication_hold(row)

    unknown_major, missing_major = validate_major_event_types()
    if unknown_major:
        sl.warning("STEP_8", f"major_event_types에 미지원 타입 존재: {sorted(unknown_major)}")
    if missing_major:
        sl.warning("STEP_8", f"권장 메이저 타입 누락: {sorted(missing_major)}")

    force_non_major = os.environ.get("PUBLISH_NON_MAJOR", "false").lower() == "true"
    if not is_major_event(event_type) and not force_non_major:
        msg = (
            f"⏭️ 발행 스킵 — episode={episode_id} event_type={event_type}는 비-메이저 이벤트입니다. "
            "굵직한 이벤트(BATTLE/SHOCK/AFTERMATH 등)만 자동 발행합니다. "
            "비-메이저 발행이 필요하면 PUBLISH_NON_MAJOR=true 후 재실행하세요."
        )
        sl.info("STEP_8", msg)
        logger.info(msg)
        return

    # ── 중복 발행 방어 (Layer 1) ─────────────────────────────────────────
    # 1) 이미 published 상태면 차단 (FORCE_REPUBLISH=true 환경변수로만 우회)
    current_status = row.get("status", "")
    force_republish = os.environ.get("FORCE_REPUBLISH", "false").lower() == "true"
    if current_status == "published" and not force_republish and not args.video_only:
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
        if dup_rows.data and not force_republish and not args.video_only:
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
        sl.error("STEP_8", f"published_comics 중복 체크 실패 — 발행 보류: {exc}")
        raise

    channels = args.channels.lower().split(",")
    battle_video_plan = build_battle_video_plan(
        row=row,
        event_type=event_type,
        script_dict=script_dict,
        channels=channels,
    )
    tweet_ids: list[str] = []
    telegram_sent = False
    telegram_receipts: dict[str, list[int]] = {}

    ts_total = time.monotonic()
    sl.info(
        "STEP_8",
        f"발행 시작 channels={channels} dry_run={dry_run} video_only={args.video_only}",
    )

    if not args.video_only or battle_video_plan.enabled:
        from engine.quality.contracts import QualityHold
        from scripts.publish_preflight import configuration_issues

        issues = configuration_issues(channels)
        if issues:
            raise QualityHold('publication configuration missing: ' + ','.join(issues))

    # --video-only는 이미 이미지가 발행된 뒤 전투씬 mp4만 추가 업로드할 때 사용한다.
    # published 중복 방어와 slides_json 요구사항을 우회하지만, 아래 video plan은 그대로 검증한다.
    if args.video_only:
        video_failures = []
        if not battle_video_plan.enabled:
            sl.info("STEP_8_VIDEO", f"전투씬 영상 스킵 reason={battle_video_plan.reason}")
            return
        else:
            publication_token = (
                None if dry_run else claim_publication(row, episode_date, episode_no)
            )
            assert battle_video_plan.video_path is not None
            battle_video_path = battle_video_plan.video_path
            if _channel_requested(list(battle_video_plan.channels), "telegram"):
                ts = sl.step_start("STEP_8_TG_VIDEO", "Telegram 전투씬 영상 발행")
                try:
                    if dry_run:
                        logger.info(
                            "[telegram_video] DRY_RUN — 채널에 전투씬 영상 발행 시뮬레이션: %s",
                            battle_video_path,
                        )
                    else:
                        result = publish_to_free_channel(
                            video_path=str(battle_video_path),
                            episode_id=episode_id,
                            title=battle_video_plan.telegram_title,
                            hashtags=list(battle_video_plan.hashtags),
                            teaser_line=battle_video_plan.telegram_teaser,
                            paid_channel_invite_link=os.environ.get("TELEGRAM_PAID_INVITE_LINK"),
                        )
                        require_publication_id(result, "message_id")
                    sl.step_done("STEP_8_TG_VIDEO", ts, f"video={battle_video_path}")
                except Exception as exc:
                    sl.step_fail("STEP_8_TG_VIDEO", ts, exc)
                    video_failures.append("telegram")

            if _channel_requested(list(battle_video_plan.channels), "x"):
                ts = sl.step_start("STEP_8_X_VIDEO", "X 전투씬 영상 발행")
                try:
                    if dry_run:
                        logger.info(
                            "[x_video] DRY_RUN — 전투씬 영상 발행 시뮬레이션: %s",
                            battle_video_path,
                        )
                    else:
                        result = publish_video_to_x(
                            video_path=str(battle_video_path),
                            caption=battle_video_plan.x_caption,
                            episode_id=episode_id,
                        )
                        require_publication_id(result, "tweet_id")
                    sl.step_done("STEP_8_X_VIDEO", ts, f"video={battle_video_path}")
                except Exception as exc:
                    sl.step_fail("STEP_8_X_VIDEO", ts, exc)
                    video_failures.append("x")
        if video_failures:
            raise RuntimeError(f"video-only publication failed: {video_failures}")
        if battle_video_plan.enabled and not dry_run:
            sl.warning(
                "STEP_8_VIDEO",
                "영상 발행 완료 — 전용 발행 이력이 없어 hold 유지; 외부 게시물 대사 후 해제 필요",
            )
        runtime = round(time.monotonic() - ts_total, 1)
        sl.info("STEP_8", f"전투씬 영상 전용 발행 완료 runtime={runtime}s")
        logger.info("✅ 전투씬 영상 전용 발행 완료 episode_id=%s", episode_id)
        return

    # 슬라이드 경로 복원
    slides_json = row.get("slides_json", [])
    slides = [Path(s["path"]) for s in slides_json if isinstance(s, dict) and s.get("path")]

    if not slides:
        sl.error("STEP_8", "슬라이드 없음 — run_resume 먼저 실행")
        sys.exit(1)

    channels = args.channels.lower().split(",")
    battle_video_plan = build_battle_video_plan(
        row=row,
        event_type=event_type,
        script_dict=script_dict,
        channels=channels,
    )
    tweet_ids: list[str] = []
    telegram_sent = False

    ts_total = time.monotonic()
    sl.info("STEP_8", f"발행 시작 channels={channels} dry_run={dry_run}")

    if not dry_run:
        from engine.publish.telegram_publisher import _validate_slides
        from engine.quality.contracts import QualityHold

        _validate_slides(slides)
        from engine.narrative.thread_contracts import validate_thread_transitions

        errors = validate_thread_transitions(script_dict,
            (script_dict.get("_state_candidate") or {}).get("previous_episode") or {},
            script_dict.get("_resolution_review"))
        if errors:
            from engine.quality.policy import qc_finding

            qc_finding("publish_narrative", "narrative contract failed: " + ",".join(errors),
                       error_type=QualityHold)
        if script_dict.get("_state_candidate"):
            from engine.publish.manifest import validate_manifest
            from engine.publish.state_commit import require_state_ready

            validate_manifest(script_dict, slides)
            require_state_ready(episode_date, episode_no, script_dict["_state_candidate"])
        if _channel_requested(channels, "x"):
            from engine.publish.x_publisher import _guard_disclaimer

            _guard_disclaimer(script_dict.get("caption_x_final", ""))
        if _channel_requested(channels, "telegram") and not os.environ.get(
            "TELEGRAM_FREE_CHANNEL_ID"
        ):
            raise QualityHold("requested Telegram channel is not configured")

    # Retain a durable hold through all channel sends and history updates.
    publication_token = None if dry_run else claim_publication(row, episode_date, episode_no)
    receipt_mode = bool(script_dict.get("_state_candidate")) and not dry_run

    def persist_receipt(channel, ids):
        from engine.publish.state_commit import record_delivery

        record_delivery(episode_date, episode_no, publication_token, channel, ids)

    # X 발행
    if _channel_requested(channels, "x"):
        ts = sl.step_start("STEP_8_X", "X 발행")
        try:
            receipt_args = {"receipt_callback": lambda ids: persist_receipt("x", ids)} if receipt_mode else {}
            tweet_ids = publish_episode_x(script_dict, slides, dry_run=dry_run, **receipt_args)
            sl.step_done("STEP_8_X", ts, f"트윗 {len(tweet_ids)}개")
        except Exception as exc:
            sl.step_fail("STEP_8_X", ts, exc)

    # Telegram 발행
    if _channel_requested(channels, "telegram"):
        tg_channels = []
        free_id = os.environ.get("TELEGRAM_FREE_CHANNEL_ID", "")
        if free_id:
            tg_channels.append(free_id)

        ts = sl.step_start("STEP_8_TG", "Telegram 발행")
        try:
            receipt_args = {"receipts": telegram_receipts} if script_dict.get("_state_candidate") else {}
            if receipt_mode:
                receipt_args["receipt_callback"] = lambda channel, ids: persist_receipt("telegram:" + channel, ids)
            results = publish_episode_telegram(script_dict, slides, tg_channels, dry_run=dry_run, **receipt_args)
            telegram_sent = bool(results) and all(results.values())
            sl.step_done("STEP_8_TG", ts, f"결과: {results}")
        except Exception as exc:
            sl.step_fail("STEP_8_TG", ts, exc)

    from engine.quality.publish_guard import require_channel_success

    if not dry_run:
        require_channel_success(channels, tweet_ids, telegram_sent)

    # Optional battle-scene video publishing.
    optional_video_failures = []
    # Existing image/PIL publishing above remains the canonical comic upload path; this
    # only appends a video post when the episode is a battle event and a video asset is
    # attached to episode_assets. Any failure is logged to STEP_8_*_VIDEO and does not
    # roll back the already-completed image/PIL publication.
    if not battle_video_plan.enabled:
        sl.info("STEP_8_VIDEO", f"전투씬 영상 스킵 reason={battle_video_plan.reason}")
    else:
        assert battle_video_plan.video_path is not None
        battle_video_path = battle_video_plan.video_path
        if _channel_requested(list(battle_video_plan.channels), "telegram"):
            ts = sl.step_start("STEP_8_TG_VIDEO", "Telegram 전투씬 영상 발행")
            try:
                if dry_run:
                    logger.info(
                        "[telegram_video] DRY_RUN — 채널에 전투씬 영상 발행 시뮬레이션: %s",
                        battle_video_path,
                    )
                else:
                    result = publish_to_free_channel(
                        video_path=str(battle_video_path),
                        episode_id=episode_id,
                        title=battle_video_plan.telegram_title,
                        hashtags=list(battle_video_plan.hashtags),
                        teaser_line=battle_video_plan.telegram_teaser,
                        paid_channel_invite_link=os.environ.get("TELEGRAM_PAID_INVITE_LINK"),
                    )
                    require_publication_id(result, "message_id")
                sl.step_done("STEP_8_TG_VIDEO", ts, f"video={battle_video_path}")
            except Exception as exc:
                sl.step_fail("STEP_8_TG_VIDEO", ts, exc)
                optional_video_failures.append("telegram")

        if _channel_requested(list(battle_video_plan.channels), "x"):
            ts = sl.step_start("STEP_8_X_VIDEO", "X 전투씬 영상 발행")
            try:
                if dry_run:
                    logger.info(
                        "[x_video] DRY_RUN — 전투씬 영상 발행 시뮬레이션: %s",
                        battle_video_path,
                    )
                else:
                    result = publish_video_to_x(
                        video_path=str(battle_video_path),
                        caption=battle_video_plan.x_caption,
                        episode_id=episode_id,
                    )
                    tweet_ids.append(require_publication_id(result, "tweet_id"))
                    if receipt_mode:
                        persist_receipt("x", [tweet_ids[-1]])
                sl.step_done("STEP_8_X_VIDEO", ts, f"video={battle_video_path}")
            except Exception as exc:
                sl.step_fail("STEP_8_X_VIDEO", ts, exc)
                optional_video_failures.append("x")

    # Simulated sends never mutate production publication history.
    if dry_run:
        sl.info("STEP_8", "DRY_RUN 완료 — 발행 이력 기록 생략")
        return

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
            **({"state_candidate": script_dict["_state_candidate"],
                "telegram_receipts": telegram_receipts}
               if script_dict.get("_state_candidate") else {}),
        )
    except Exception as exc:
        sl.error("STEP_8", f"이력 기록 실패 — 대사 필요: {exc}")
        raise

    if optional_video_failures:
        from engine.quality.contracts import QualityHold

        raise QualityHold(
            f"images published; optional video requires reconciliation: {optional_video_failures}"
        )
    finish_publication(episode_date, episode_no, publication_token)
    sl.info("STEP_8", f"발행 완료 runtime={runtime}s")
    logger.info("✅ 발행 완료 episode_id=%s", episode_id)


if __name__ == "__main__":
    main()
