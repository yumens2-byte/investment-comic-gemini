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

VERSION = "1.1.0"
logger = logging.getLogger("resolve_weekly_artifact")

RESTORABLE_STATES = {"media_generated", "assembled", "pending_approval"}


class RestoreUnavailableError(RuntimeError):
    """복원해야 하는 상태인데 복원 경로가 없음 — 조용히 넘기면 안 되는 상황."""


def _emit(**kwargs) -> None:
    lines = [f"{k}={v}" for k, v in kwargs.items()]
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def _setup_file_log() -> None:
    """logs/{run_id}/resolve_artifact.log 로 남겨 artifact 에 포함시킨다.

    v1.1.0 (2026-09-07 run #34116761360 회고): 복원 step 이 건너뛰어졌는데 그 판단
    근거가 artifact 어디에도 남지 않아 원인 규명이 불가능했다.
    """
    from pathlib import Path

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    log_dir = Path("logs") / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "resolve_artifact.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    # basicConfig 는 root 에 핸들러가 이미 있으면 레벨을 바꾸지 않는다(기본 WARNING).
    # 그 경우 INFO 진단 로그가 통째로 유실되므로 명시적으로 낮춘다.
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)


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
    logger.info("[resolve] 대상 판정: episode_id=%s row=%s", episode_id, row)

    if not row:
        logger.info("[resolve] %s 기존 행 없음 — 신규 주차 (복원 불필요)", episode_id)
        return None

    status = row.get("status")
    run_id = row.get("artifact_run_id")
    if status not in RESTORABLE_STATES:
        logger.info("[resolve] status=%s — 복원 대상 아님 (신규 생성 경로)", status)
        return None
    if not run_id:
        # v1.1.0: 조용히 넘기면 W6 이 "W4/W5 선행 필요" 로 실패해 원인을 오인하게 된다.
        # 미디어는 있는데 복원 경로가 없다는 사실을 즉시 알린다.
        raise RestoreUnavailableError(
            f"{episode_id} status={status} 인데 artifact_run_id 가 없습니다. "
            "이전 실행의 산출물을 찾을 수 없어 재조립이 불가능합니다. "
            "force_regenerate=true 로 재생성하거나 artifact_run_id 를 보정하십시오."
        )

    logger.info("[resolve] 복원 대상: %s (status=%s, run_id=%s)", episode_id, status, run_id)
    return {"episode_id": episode_id, "run_id": str(run_id)}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    _setup_file_log()
    logger.info("[resolve_weekly_artifact] v%s 시작", VERSION)

    try:
        target = resolve()
    except RestoreUnavailableError as exc:
        logger.error("[resolve] %s", exc)
        _emit(found="false", run_id="", episode_id="")
        return 1
    except Exception:
        # v1.1.0: 과거엔 조용히 found=false 로 넘겨 W6 실패 원인을 가렸다.
        # DB 는 W1 게이트에서 이미 사용되므로, 여기서의 조회 실패는 비정상이다.
        logger.exception("[resolve] 조회 실패 — 복원 여부를 판단할 수 없음")
        _emit(found="false", run_id="", episode_id="")
        return 1

    if target is None:
        _emit(found="false", run_id="", episode_id="")
        return 0

    _emit(found="true", run_id=target["run_id"], episode_id=target["episode_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
