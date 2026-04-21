"""
scripts/resolve_episode.py
pre-check job: episode_id + slides_run_id 결정 → GITHUB_OUTPUT 출력

출력 (>> $GITHUB_OUTPUT):
  episode_id=ICG-2026-04-15-004
  slides_run_id=24732938765   (없으면 빈 문자열)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("icg.resolve_episode")

# assembled → image_generated 순서로 조회 (run_publish.py 동일 기준)
RESOLVABLE_STATUSES = ("assembled", "image_generated")


def resolve_from_supabase(episode_id_input: str) -> dict:
    """
    episode_id 입력 시: 해당 에피소드 row 반환
    미입력 시: 최신 assembled/image_generated row 반환

    반환: {"episode_id": str, "github_run_id": str | None}
    """
    from engine.common.supabase_client import icg_table

    if episode_id_input:
        # episode_id → episode_date + episode_no 파싱
        parts = episode_id_input.split("-")
        if len(parts) < 5:
            logger.error("잘못된 episode_id 형식: %s", episode_id_input)
            sys.exit(1)

        episode_date = "-".join(parts[1:4])   # 2026-04-15
        episode_no   = int(parts[4])           # 004 → 4

        rows = (
            icg_table("episode_assets")
            .select("episode_date, episode_no, status, github_run_id")
            .eq("episode_date", episode_date)
            .eq("episode_no", episode_no)
            .limit(1)
            .execute()
        )
        if not rows.data:
            logger.error("episode_assets 없음: %s", episode_id_input)
            sys.exit(1)

        row = rows.data[0]
        return {
            "episode_id":    episode_id_input,
            "github_run_id": row.get("github_run_id") or "",
        }

    # 미입력: 최신 resolvable 에피소드 자동 선택
    for status in RESOLVABLE_STATUSES:
        rows = (
            icg_table("episode_assets")
            .select("episode_date, episode_no, status, github_run_id")
            .eq("status", status)
            .order("episode_date", desc=True)
            .order("episode_no", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            row = rows.data[0]
            ep_date = str(row["episode_date"])
            ep_no   = row.get("episode_no") or 1
            ep_id   = f"ICG-{ep_date}-{ep_no:03d}"
            logger.info("자동 선택: %s (status=%s)", ep_id, status)
            return {
                "episode_id":    ep_id,
                "github_run_id": row.get("github_run_id") or "",
            }

    logger.error("발행 가능한 에피소드 없음 (assembled/image_generated 없음)")
    sys.exit(1)


def find_slides_run_id_from_github(episode_id: str, gh_token: str) -> str:
    """
    github_run_id가 Supabase에 없을 때 GitHub API fallback.
    slides-{episode_id} 아티팩트를 가진 최근 run을 탐색.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or not gh_token:
        return ""

    url = f"https://api.github.com/repos/{repo}/actions/artifacts"
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
    }
    params = {"per_page": 30, "name": f"slides-{episode_id}"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        artifacts = resp.json().get("artifacts", [])
        if artifacts:
            run_id = str(artifacts[0]["workflow_run"]["id"])
            logger.info("GitHub API fallback — slides_run_id=%s", run_id)
            return run_id
    except Exception as exc:
        logger.warning("GitHub API 탐색 실패 (slides_run_id 없음): %s", exc)

    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-id", default="", help="에피소드 ID (미입력 시 자동 선택)")
    args = parser.parse_args()

    episode_id_input = args.episode_id.strip() or os.environ.get("INPUT_EPISODE_ID", "").strip()
    gh_token         = os.environ.get("GH_TOKEN", "")

    result = resolve_from_supabase(episode_id_input)

    episode_id    = result["episode_id"]
    slides_run_id = result["github_run_id"]

    # Supabase에 run_id 없으면 GitHub API fallback
    if not slides_run_id and gh_token:
        slides_run_id = find_slides_run_id_from_github(episode_id, gh_token)

    # GITHUB_OUTPUT 출력
    print(f"episode_id={episode_id}")
    print(f"slides_run_id={slides_run_id}")

    logger.info("episode_id=%s slides_run_id=%s", episode_id, slides_run_id or "(없음)")


if __name__ == "__main__":
    main()
