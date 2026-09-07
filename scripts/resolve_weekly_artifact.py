"""
scripts/resolve_weekly_artifact.py
주간 다이제스트 — 선행 실행 산출물(artifact) 복원 대상 해석.

배경 (2026-09-07 run #34101547854 회고):
  W4/W5 가 미디어를 생성한 뒤 W6 조립이 실패/스킵되면, 다음 실행은 깨끗한 러너에서
  시작하므로 output/videos/... 파일이 없어 재조립이 불가능했다. 유일한 복구 수단이
  전체 재생성($1.88 재과금)이었다.
  → video_assets.artifact_run_id 로 이전 실행의 artifact 를 복원해 재과금 0 으로
    조립만 다시 수행할 수 있게 한다.

출력 (GITHUB_OUTPUT):
  found=true|false, run_id=<GitHub run id>, episode_id=<...>

정책:
  - status 가 media_generated / assembled / pending_approval 이고 artifact_run_id 가
    있을 때만 복원 대상이다 (생성 전 상태는 복원할 것이 없다).
  - 대상이 없으면 found=false 로 정상 종료(rc=0). 신규 주차의 정상 경로다.

VERSION 이력:
  1.0.0  최초
"""

from __future__ import annotations

import logging
import os
import sys

VERSION = "1.0.0"
logger = logging.getLogger("resolve_weekly_artifact")

RESTORABLE_STATES = {"media_generated", "assembled", "pending_approval"}


def _emit(**kwargs) -> None:
    lines = [f"{k}={v}" for k, v in kwargs.items()]
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def resolve() -> dict | None:
    """이번 주차에 복원할 artifact 가 있으면 그 정보를 돌려준다."""
    from engine.video.weekly_pipeline import (
        _load_video_asset_row,
        build_weekly_episode_id,
        resolve_week_window,
    )

    _, week_end = resolve_week_window()
    episode_id = build_weekly_episode_id(week_end)

    row = _load_video_asset_row(episode_id)
    if not row:
        logger.info("[resolve] %s 기존 행 없음 — 신규 주차 (복원 불필요)", episode_id)
        return None

    status = row.get("status")
    run_id = row.get("artifact_run_id")
    if status not in RESTORABLE_STATES:
        logger.info("[resolve] status=%s — 복원 대상 아님", status)
        return None
    if not run_id:
        logger.warning(
            "[resolve] %s status=%s 인데 artifact_run_id 없음 — 복원 불가 "
            "(재조립하려면 force_regenerate 필요, 비용 재발생)",
            episode_id,
            status,
        )
        return None

    logger.info("[resolve] 복원 대상: %s (status=%s, run_id=%s)", episode_id, status, run_id)
    return {"episode_id": episode_id, "run_id": str(run_id)}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    logger.info("[resolve_weekly_artifact] v%s 시작", VERSION)

    try:
        target = resolve()
    except Exception:
        # 복원 해석 실패가 파이프라인 전체를 막아서는 안 된다 (신규 생성은 계속 가능).
        logger.exception("[resolve] 조회 실패 — 복원 없이 진행")
        _emit(found="false", run_id="", episode_id="")
        return 0

    if target is None:
        _emit(found="false", run_id="", episode_id="")
        return 0

    _emit(found="true", run_id=target["run_id"], episode_id=target["episode_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
