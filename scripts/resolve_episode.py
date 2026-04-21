"""
scripts/resolve_episode.py
publish_sns.yml pre-check job에서 사용.

Supabase icg.episode_assets에서 발행 대상 에피소드를 결정하고,
episode_id + slides_run_id를 GITHUB_OUTPUT으로 출력.

사용법:
  python -m scripts.resolve_episode                              # 최신 assembled 자동 선택
  python -m scripts.resolve_episode --episode-id ICG-2026-04-22-001

출력 (stdout, GITHUB_OUTPUT):
  episode_id=ICG-2026-04-22-001
  slides_run_id=24732746246
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("icg.resolve_episode")

# run_publish.py와 동일한 우선순위
# 주의: image_generated 상태는 slides_run_id가 null일 수 있음 → 발행 불가
# 따라서 자동 선택 시에는 assembled만 허용
RESOLVABLE_STATUSES = ("assembled",)


def _parse_episode_id(episode_id: str) -> tuple[str, int]:
    """ICG-YYYY-MM-DD-NNN → (YYYY-MM-DD, NNN)"""
    m = re.match(r"ICG-(\d{4}-\d{2}-\d{2})-(\d{3})", episode_id)
    if not m:
        raise ValueError(f"잘못된 episode_id 형식: {episode_id}")
    return m.group(1), int(m.group(2))


def resolve(episode_id_input: str) -> dict:
    """
    episode_id 입력 시: 해당 에피소드 조회
    미입력 시: 최신 assembled 에피소드 자동 선택

    Returns:
        {"episode_id": str, "slides_run_id": str}
        slides_run_id는 DB에 NULL이면 빈 문자열 ("")
    """
    from engine.common.supabase_client import icg_table

    if episode_id_input:
        # 명시적 지정 — 해당 row 조회
        try:
            episode_date, episode_no = _parse_episode_id(episode_id_input)
        except ValueError as exc:
            logger.error("%s", exc)
            sys.exit(1)

        rows = (
            icg_table("episode_assets")
            .select("episode_date, episode_no, status, slides_run_id")
            .eq("episode_date", episode_date)
            .eq("episode_no", episode_no)
            .limit(1)
            .execute()
        )
        if not rows.data:
            logger.error("episode_assets 없음: %s", episode_id_input)
            sys.exit(1)

        row = rows.data[0]
        status = row.get("status", "")
        if status not in ("assembled", "image_generated", "published"):
            logger.warning(
                "발행 가능 상태 아님: %s (status=%s) — 계속 진행",
                episode_id_input,
                status,
            )

        return {
            "episode_id":    episode_id_input,
            "slides_run_id": row.get("slides_run_id") or "",
        }

    # 미입력 — 최신 assembled 자동 선택
    for status in RESOLVABLE_STATUSES:
        rows = (
            icg_table("episode_assets")
            .select("episode_date, episode_no, status, slides_run_id")
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
                "slides_run_id": row.get("slides_run_id") or "",
            }

    logger.error("발행 가능한 에피소드 없음 (status=assembled 없음)")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG 에피소드 + slides_run_id 결정")
    parser.add_argument("--episode-id", default="", help="에피소드 ID (미입력 시 자동 선택)")
    args = parser.parse_args()

    episode_id_input = args.episode_id.strip()
    result = resolve(episode_id_input)

    # stdout에 GITHUB_OUTPUT 형식으로 출력
    # publish_sns.yml: `python -m scripts.resolve_episode ... >> $GITHUB_OUTPUT`
    print(f"episode_id={result['episode_id']}")
    print(f"slides_run_id={result['slides_run_id']}")

    logger.info(
        "episode_id=%s slides_run_id=%s",
        result["episode_id"],
        result["slides_run_id"] or "(없음 — 아티팩트 다운로드 skip)",
    )


if __name__ == "__main__":
    main()
