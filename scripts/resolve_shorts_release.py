"""
scripts/resolve_shorts_release.py
지연 자동발행(hold-and-release) 대상 해석 — Publish Shorts 워크플로 전용.

설계 (2026-08-29 마스터 지시: "ICG처럼 시간 텀 두고 발행, 확인하고 중단"):
  daily_shorts 가 조립을 끝내면 status='pending_approval' + release_at 을 기록한다.
  본 스크립트는 release_at 이 지난 건만 발행 대상으로 선택한다.
  마스터는 그 사이에 abort 로 중단할 수 있다 (기본은 발행, 개입하면 중단).

선택 조건 (AND):
  1) status = 'pending_approval'          (조립 완료 + 승인 대기)
  2) release_at <= now()                  (홀드 시간 경과)
  3) youtube_video_id IS NULL             (미발행 — 중복 발행 차단)
  4) artifact_run_id IS NOT NULL          (mp4 복원 가능)

출력: GITHUB_OUTPUT 형식 (episode_id / artifact_run_id / found)
  대상이 없으면 found=false 로 정상 종료(rc=0) — 스케줄 실행의 정상 케이스다.

VERSION 이력:
  1.0.0  최초 (hold-and-release)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

VERSION = "1.0.0"
logger = logging.getLogger("resolve_shorts_release")


def _emit(**kwargs) -> None:
    """GITHUB_OUTPUT (없으면 stdout) 으로 key=value 출력."""
    lines = [f"{k}={v}" for k, v in kwargs.items()]
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def resolve(episode_id: str = "") -> dict | None:
    """발행 대상 1건을 선택한다 (없으면 None)."""
    from engine.common.supabase_client import icg_table

    query = (
        icg_table("video_assets")
        .select("episode_id, episode_date, status, release_at, artifact_run_id, youtube_video_id")
        .eq("status", "pending_approval")
        .is_("youtube_video_id", "null")
        .order("episode_date", desc=True)
        .limit(5)
    )
    if episode_id:
        query = query.eq("episode_id", episode_id)

    rows = query.execute().data or []
    if not rows:
        logger.info("[resolve] pending_approval 대상 없음")
        return None

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for row in rows:
        eid = row["episode_id"]
        release_at = row.get("release_at")
        if not release_at:
            logger.warning("[resolve] %s release_at 미기록 — 건너뜀", eid)
            continue
        released = datetime.fromisoformat(str(release_at).replace("Z", "+00:00"))
        if released > now:
            remaining = (released - now).total_seconds() / 60
            logger.info(
                "[resolve] %s 홀드 중 — 발행까지 %.0f분 남음 (release_at=%s)",
                eid,
                remaining,
                release_at,
            )
            continue
        if not row.get("artifact_run_id"):
            logger.warning("[resolve] %s artifact_run_id 없음 — mp4 복원 불가", eid)
            continue
        logger.info("[resolve] 발행 대상 확정: %s (release_at=%s)", eid, release_at)
        return row

    return None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    logger.info("[resolve_shorts_release] v%s 시작", VERSION)

    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-id", default="", help="특정 에피소드 지정 (미지정 시 자동)")
    args = parser.parse_args()

    try:
        row = resolve(args.episode_id.strip())
    except Exception:
        logger.exception("[resolve] 조회 실패")
        return 1

    if row is None:
        _emit(found="false", episode_id="", episode_date="", artifact_run_id="")
        logger.info("[resolve] 발행 대상 없음 — 정상 종료")
        return 0

    _emit(
        found="true",
        episode_id=row["episode_id"],
        # 러너(_resolve_target_date)는 YYYY-MM-DD 를 기대하므로 날짜를 별도 출력한다.
        episode_date=str(row["episode_date"]),
        artifact_run_id=row["artifact_run_id"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
