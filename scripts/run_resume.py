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


def _latest_episode_id(
    *,
    include_assembled: bool = False,
    allow_narrative_only: bool = False,
) -> str | None:
    """
    Supabase에서 가장 최신의 재처리 가능한 에피소드 ID 반환.

    기본 자동 선택은 image_generated만 허용한다. assembled 재조립은
    명시적 --force/--include-assembled 또는 --episode 지정 시 status guard를
    통과해야 하며, narrative_done 조립은 --allow-narrative-only가 필요하다.
    """
    try:
        from engine.common.supabase_client import icg_table

        statuses = ["image_generated"]
        if include_assembled:
            statuses.append("assembled")
        if allow_narrative_only:
            statuses.append("narrative_done")

        for status in statuses:
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


def guard_resume_status(status: str, *, force: bool, allow_narrative_only: bool) -> None:
    """Resume 대상 status 검증.

    - image_generated: 정상 조립 허용
    - assembled: --force가 있을 때만 재조립 허용
    - narrative_done: --allow-narrative-only가 있을 때만 text-card 가능성을 감수하고 허용
    - published/failed/aborted 등은 기본 차단
    """
    status = status or ""
    if status == "image_generated":
        return
    if status == "assembled" and force:
        return
    if status == "narrative_done" and allow_narrative_only:
        return
    if status == "published":
        raise RuntimeError("published 에피소드는 Resume Episode로 재조립할 수 없습니다.")
    if status == "assembled":
        raise RuntimeError("assembled 에피소드 재조립은 --force가 필요합니다.")
    if status == "narrative_done":
        raise RuntimeError("narrative_done 에피소드 조립은 --allow-narrative-only가 필요합니다.")
    raise RuntimeError(f"Resume Episode 실행 불가 status={status!r}")


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
    parser.add_argument("--force", action="store_true", help="assembled 상태 재조립 허용")
    parser.add_argument(
        "--allow-narrative-only",
        action="store_true",
        help="이미지 생성 전 narrative_done 상태도 조립 허용 (text_card fallback 가능)",
    )
    args = parser.parse_args()

    # 빈 문자열("") 입력 시 None으로 처리 (yml에서 미입력 시 "" 전달되는 경우)
    episode_id = (args.episode or None) and args.episode.strip() or None
    explicit_episode = bool(episode_id)
    episode_id = episode_id or _latest_episode_id(
        include_assembled=False,
        allow_narrative_only=args.allow_narrative_only,
    )
    if not episode_id:
        logger.error("❌ 실행 가능한 에피소드 없음 (image_generated 상태 없음)")
        sys.exit(1)
    logger.info("[run_resume] 대상 에피소드: %s", episode_id)
    episode_date = _parse_date(episode_id)

    from engine.assembly.pil_composer import compose_episode
    from engine.common.logger import StepLogger, get_run_id
    from engine.common.supabase_client import icg_table
    from engine.persist.asset_writer import patch_by_episode as asset_patch_by_episode

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
        sl.error("STEP_7", f"episode_assets row 없음: episode_id={episode_id}")
        sys.exit(1)

    status = row.get("status", "")
    try:
        guard_resume_status(
            status,
            force=args.force,
            allow_narrative_only=args.allow_narrative_only,
        )
    except RuntimeError as exc:
        sl.error("STEP_7", str(exc))
        sys.exit(1)

    if explicit_episode and status == "assembled" and args.force:
        sl.info("STEP_7", "assembled 에피소드 강제 재조립 허용 (--force)")
    if status == "narrative_done" and args.allow_narrative_only:
        sl.warning("STEP_7", "narrative_done 상태 조립 허용 — 이미지 없는 text_card fallback 가능")

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
        import os as _os

        slides_json = [{"idx": i + 1, "path": str(s)} for i, s in enumerate(slides)]
        slides_run_id = _os.environ.get("GITHUB_RUN_ID")  # publish_sns.yml 아티팩트 다운로드용

        fallback_count = sum(1 for p in panel_images if p is None or not p.exists())
        fallback_count += max(0, len(panels) - len(panel_images))

        # episode_no 기준 patch — script_json 등 기존 컬럼 보존, 동일 event_type row 덮어쓰기 방지
        asset_patch_by_episode(
            episode_date,
            episode_no,
            {
                "slides_json": slides_json,
                "dialog_edited": bool(dialog_edits),
                "status": "assembled",
                "slides_run_id": slides_run_id,  # 슬라이드 아티팩트 run_id 저장
            },
        )
        if fallback_count:
            sl.warning(
                "STEP_7_PIL",
                f"패널 이미지 {fallback_count}개 누락/미존재 — text_card fallback 포함",
            )

        if slides_run_id:
            sl.info("STEP_7_PIL", f"slides_run_id={slides_run_id} → DB 저장 완료")
            # GITHUB_OUTPUT에도 출력 (publish_sns.yml에서 참조 가능)
            gha_output = _os.environ.get("GITHUB_OUTPUT", "")
            if gha_output:
                with open(gha_output, "a") as f:
                    f.write(f"slides_run_id={slides_run_id}\n")

        sl.step_done("STEP_7_PIL", ts, f"슬라이드 {len(slides)}개 조립 완료")
        logger.info("✅ 조립 완료: %s", slides_dir)
        logger.info("📤 다음 단계: run_publish.py --episode %s", episode_id)

    except Exception as exc:
        sl.step_fail("STEP_7_PIL", ts, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
