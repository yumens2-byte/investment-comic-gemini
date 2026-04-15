"""
scripts/run_resume.py
Dialog 주입 후 PIL 조립 재개 (STEP 7).

사용법:
  python -m scripts.run_resume --episode ICG-2026-04-14-001
  python -m scripts.run_resume --episode ICG-2026-04-14-001 --force
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("icg.run_resume")


def _parse_date(episode_id: str) -> str:
    """ICG-YYYY-MM-DD-NNN → YYYY-MM-DD."""
    m = re.match(r"ICG-(\d{4}-\d{2}-\d{2})-\d{3}", episode_id)
    if not m:
        raise ValueError(f"잘못된 episode_id 형식: {episode_id}")
    return m.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG 에피소드 재개 (STEP 7 PIL 조립)")
    parser.add_argument("--episode", required=True, help="에피소드 ID (ICG-YYYY-MM-DD-001)")
    parser.add_argument("--force", action="store_true", help="assembled 상태 덮어쓰기")
    args = parser.parse_args()

    episode_id = args.episode
    episode_date = _parse_date(episode_id)

    from engine.assembly.pil_composer import compose_episode
    from engine.common.logger import StepLogger, get_run_id
    from engine.common.supabase_client import icg_table
    from engine.persist.asset_writer import patch as asset_patch

    run_id = get_run_id(episode_date)
    output_dir = Path("output") / "episodes" / episode_date
    sl = StepLogger(run_id=run_id, episode_date=episode_date, output_dir=output_dir)

    sl.info("STEP_7", f"PIL 조립 시작 episode_id={episode_id}")

    # episode_assets 로드 — episode_id로 직접 조회 (event_type None 회피)
    episode_no = int(episode_id.split("-")[-1])
    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .eq("episode_no", episode_no)
        .limit(1)
        .execute()
    )
    row = rows.data[0] if rows.data else None

    if not row:
        # fallback: 날짜 기준 최신 row
        rows = (
            icg_table("episode_assets")
            .select("*")
            .eq("episode_date", episode_date)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = rows.data[0] if rows.data else None
        if row:
            sl.info(
                "STEP_7",
                f"episode_no 조회 실패 → 최신 row fallback (event_type={row.get('event_type')})",
            )

    if not row:
        sl.error("STEP_7", f"episode_assets row 없음: date={episode_date}")
        sys.exit(1)

    event_type = row.get("event_type", "NORMAL")
    script_dict = row.get("script_json", {})
    dialog_edits = row.get("dialog_edits_json", {})

    # dialog edits 적용
    if dialog_edits and dialog_edits.get("edits"):
        panels = script_dict.get("panels", [])
        edits_map = {e["idx"]: e for e in dialog_edits["edits"]}
        for panel in panels:
            idx = panel.get("idx", 0)
            if idx in edits_map:
                edit = edits_map[idx]
                if "key_text" in edit:
                    panel["key_text"] = edit["key_text"]
                if "narration" in edit:
                    panel["narration"] = edit["narration"]
        sl.info("STEP_7", f"dialog edits 적용: {len(edits_map)}개 패널 수정")

    # 패널 이미지 경로 복원
    panels_json = row.get("panels_json", [])
    panel_images = []
    for p in panels_json:
        path_str = p.get("path") if isinstance(p, dict) else None
        panel_images.append(Path(path_str) if path_str else None)

    # PIL 조립
    ts = sl.step_start("STEP_7_PIL", "슬라이드 조립")
    try:
        slides_dir = output_dir / "slides"
        panels = script_dict.get("panels", [])
        slides = compose_episode(panels, panel_images, slides_dir)

        # slides_json 업데이트
        slides_json = [{"idx": i + 1, "path": str(s)} for i, s in enumerate(slides)]
        # patch 사용 — script_json 등 기존 컬럼 보존
        asset_patch(
            episode_date,
            event_type,
            {
                "slides_json": slides_json,
                "dialog_edited": bool(dialog_edits),
                "status": "assembled",
            },
        )

        sl.step_done("STEP_7_PIL", ts, f"슬라이드 {len(slides)}개 조립 완료")
        logger.info("✅ 조립 완료: %s", slides_dir)
        logger.info("📤 다음 단계: run_publish.py --episode %s", episode_id)

    except Exception as exc:
        sl.step_fail("STEP_7_PIL", ts, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
