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


def _latest_episode_id() -> str | None:
    """
    Supabase에서 가장 최신의 재처리 가능한 에피소드 ID 반환.
    우선순위: image_generated → assembled (재조립) → narrative_done
    """
    try:
        from engine.common.supabase_client import icg_table

        for status in ("image_generated", "assembled", "narrative_done"):
            rows = (
                icg_table("episode_assets")
                .select("episode_date, episode_no")
                .eq("status", status)
                .order("episode_date", desc=True)
                .order("episode_no", desc=True)
                .limit(1)
                .execute()
            )
            if rows.data:
                row = rows.data[0]
                ep_date = str(row["episode_date"])
                ep_no = row.get("episode_no") or 1
                logger.info(
                    "[run_resume] 자동 선택: %s (status=%s)", f"ICG-{ep_date}-{ep_no:03d}", status
                )
                return f"ICG-{ep_date}-{ep_no:03d}"
    except Exception as exc:
        logger.warning("[run_resume] 최신 에피소드 조회 실패: %s", exc)
    return None


def _get_artifact_run_id(episode_date: str, event_type: str) -> str | None:
    """episode_assets에서 artifact_run_id 조회."""
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("episode_assets")
            .select("artifact_run_id")
            .eq("episode_date", episode_date)
            .eq("event_type", event_type)
            .limit(1)
            .execute()
        )
        if rows.data:
            return rows.data[0].get("artifact_run_id")
    except Exception:
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG 에피소드 재개 (STEP 7 PIL 조립)")
    parser.add_argument(
        "--episode",
        default=None,
        help="에피소드 ID (ICG-YYYY-MM-DD-001). 미입력 시 최신 image_generated 에피소드 자동 선택.",
    )
    parser.add_argument("--force", action="store_true", help="assembled 상태 덮어쓰기")
    args = parser.parse_args()

    # 빈 문자열("") 입력 시 None으로 처리 (yml에서 미입력 시 "" 전달되는 경우)
    episode_id = (args.episode or None) and args.episode.strip() or None
    episode_id = episode_id or _latest_episode_id()
    if not episode_id:
        logger.error("❌ 실행 가능한 에피소드 없음 (image_generated 상태 없음)")
        sys.exit(1)
    logger.info("[run_resume] 대상 에피소드: %s", episode_id)
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

    # artifact_run_id 출력 (yml의 다운로드 step에서 활용)
    artifact_run_id = row.get("artifact_run_id")
    if artifact_run_id:
        sl.info("STEP_7", f"artifact_run_id={artifact_run_id}")
        # GitHub Actions 출력 변수로 설정 (워크플로우에서 참조 가능)
        import os as _os

        gha_output = _os.environ.get("GITHUB_OUTPUT", "")
        if gha_output:
            with open(gha_output, "a") as f:
                f.write(f"artifact_run_id={artifact_run_id}\n")
    else:
        sl.info("STEP_7", "artifact_run_id 없음 — 아티팩트 없이 진행 (text_card fallback 가능)")

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
