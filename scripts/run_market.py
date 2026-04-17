"""
scripts/run_market.py
ICG 파이프라인 메인 진입점 — STEP 2~6.

사용법:
  python -m scripts.run_market --stage all --date 2026-04-14
  python -m scripts.run_market --stage data
  python -m scripts.run_market --stage analysis
  python -m scripts.run_market --stage narrative
  python -m scripts.run_market --stage persist
  python -m scripts.run_market --stage image
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("icg.run_market")


def _today() -> str:
    """KST 오늘 날짜 (YYYY-MM-DD)."""
    return date.today().strftime("%Y-%m-%d")


def _latest_date(stage: str) -> str:
    """
    날짜 미입력 시 기준 날짜 결정.
    - stage=all/data: 오늘 날짜 (신규 수집)
    - stage=analysis/narrative/persist/image: Supabase 최신 daily_snapshots 날짜
      → 없으면 오늘 날짜 fallback.
    """
    if stage in ("all", "data"):
        return _today()
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("daily_snapshots")
            .select("snapshot_date")
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            return str(rows.data[0]["snapshot_date"])
    except Exception:
        pass
    return _today()


def _make_episode_id(episode_date: str) -> str:
    """에피소드 ID 생성: ICG-YYYY-MM-DD-001."""
    from engine.common.supabase_client import icg_table

    try:
        rows = (
            icg_table("episode_assets")
            .select("episode_no")
            .eq("episode_date", episode_date)
            .order("episode_no", desc=True)
            .limit(1)
            .execute()
        )
        last_no = rows.data[0]["episode_no"] if rows.data else 0
        no = (last_no or 0) + 1
    except Exception:
        no = 1

    return f"ICG-{episode_date}-{no:03d}"


def step_data(episode_date: str, logger_inst) -> None:
    """STEP 2: 시장 데이터 수집 → icg.daily_snapshots."""
    ts = logger_inst.step_start("STEP_2", "데이터 수집")
    try:
        from engine.data import (
            crypto_fetcher,
            feargreed_fetcher,
            fred_fetcher,
            market_fetcher,
            sentiment_fetcher,
        )
        from engine.data.snapshot_writer import upsert

        fred = fred_fetcher.fetch_all(episode_date)
        market = market_fetcher.fetch_all(episode_date)
        fg = feargreed_fetcher.fetch_all(episode_date)
        crypto = crypto_fetcher.fetch_all(episode_date)
        sentiment = sentiment_fetcher.fetch_all(episode_date)

        upsert(episode_date, fred, market, fg, crypto, sentiment)
        logger_inst.step_done("STEP_2", ts, "daily_snapshots upsert 완료")
    except Exception as exc:
        logger_inst.step_fail("STEP_2", ts, exc)
        raise


def step_analysis(episode_date: str, logger_inst) -> dict:
    """STEP 3: 분석 + Battle → icg.daily_analysis. context dict 반환."""
    ts = logger_inst.step_start("STEP_3", "분석/Battle 계산")
    try:
        import yaml

        from engine.analysis.analysis_writer import upsert as analysis_upsert
        from engine.analysis.delta_engine import compute
        from engine.analysis.event_classifier import classify, get_market_context_for_battle
        from engine.analysis.reader import get_latest
        from engine.narrative.battle_calc import (
            battle,
            select_characters_for_event,
        )

        rows = get_latest(2)
        if not rows:
            raise RuntimeError("daily_snapshots에 데이터 없음 — STEP 2 먼저 실행")

        curr_row = rows[0]
        prev_row = rows[1] if len(rows) > 1 else None

        delta = compute(curr_row, prev_row)

        arc_context = {"tension": 40, "days_since_last": 0, "yesterday_type": "NORMAL"}
        event_type = classify(delta, arc_context)

        hero_id, villain_id = select_characters_for_event(event_type, delta)

        # characters.yaml에서 base_power 로드
        canon = yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))
        # base_power — Notion battle_constants에서 로드 (yaml 값은 마스킹됨)
        try:
            from engine.common.notion_loader import load_battle_constants

            _bp_tbl = load_battle_constants().get("CHARACTER_BASE_POWER", {})
            hero_base = _bp_tbl.get(hero_id, canon["heroes"][hero_id].get("base_power", 75))
            villain_base = _bp_tbl.get(
                villain_id, canon["villains"][villain_id].get("base_power", 72)
            )
        except Exception:
            hero_base = canon["heroes"][hero_id].get("base_power", 75)
            villain_base = canon["villains"][villain_id].get("base_power", 72)

        market_ctx = get_market_context_for_battle(delta, curr_row)
        battle_result = battle(
            hero_id=hero_id,
            hero_base=hero_base,
            villain_id=villain_id,
            villain_base=villain_base,
            market_context=market_ctx,
            arc_context=arc_context,
        )

        analysis_upsert(episode_date, event_type, battle_result.to_dict(), delta, arc_context)

        ctx = {
            "event_type": event_type,
            "delta": delta,
            "battle_result": battle_result.to_dict(),
            "hero_id": hero_id,
            "villain_id": villain_id,
            "arc_context": arc_context,
        }
        logger_inst.step_done("STEP_3", ts, f"event={event_type} outcome={battle_result.outcome}")
        return ctx
    except Exception as exc:
        logger_inst.step_fail("STEP_3", ts, exc)
        raise


def step_narrative(episode_date: str, episode_id: str, ctx: dict, logger_inst) -> dict:
    """STEP 4: Claude 스토리 생성 → EpisodeScript."""
    ts = logger_inst.step_start("STEP_4", "Claude 내러티브 생성")
    try:
        from engine.narrative.claude_client import generate_episode

        script = generate_episode(
            date=episode_date,
            episode_id=episode_id,
            event_type=ctx["event_type"],
            delta=ctx["delta"],
            battle_result=ctx["battle_result"],
            hero_id=ctx["hero_id"],
            villain_id=ctx["villain_id"],
            arc_context=ctx["arc_context"],
        )
        script_dict = script.model_dump()

        # 에피소드 JSON 파일 저장 (로그 아카이브)
        ep_dir = Path("output") / "episodes" / episode_date
        ep_dir.mkdir(parents=True, exist_ok=True)
        ep_json_path = ep_dir / f"{episode_id}_script.json"
        ep_json_path.write_text(
            __import__("json").dumps(script_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger_inst.step_done(
            "STEP_4",
            ts,
            f"패널 {len(script.panels)}개 생성 | JSON 저장: {ep_json_path}",
        )
        return script_dict
    except Exception as exc:
        logger_inst.step_fail("STEP_4", ts, exc)
        raise


def step_persist(
    episode_date: str, episode_id: str, ctx: dict, script_dict: dict, logger_inst
) -> None:
    """STEP 5: Supabase + Notion 적재."""
    ts = logger_inst.step_start("STEP_5", "Supabase/Notion 적재")
    try:
        from engine.persist.asset_writer import upsert as asset_upsert
        from engine.persist.notion_mirror import create_or_update

        asset_upsert(
            episode_date,
            ctx["event_type"],
            {
                "episode_no": int(episode_id.split("-")[-1]),
                "title": script_dict.get("title", ""),
                "script_json": script_dict,
                "battle_json": ctx["battle_result"],
                "status": "narrative_done",
            },
        )

        create_or_update(
            episode_date=episode_date,
            episode_id=episode_id,
            title=script_dict.get("title", ""),
            event_type=ctx["event_type"],
            status="narrative_done",
            hero_id=ctx["hero_id"],
            villain_id=ctx["villain_id"],
            outcome=ctx["battle_result"].get("outcome", "DRAW"),
            balance=ctx["battle_result"].get("balance", 0),
            panel_count=len(script_dict.get("panels", [])),
            log_path=f"output/episodes/{episode_date}/run.log",
        )

        logger_inst.step_done("STEP_5", ts, "적재 완료")
    except Exception as exc:
        logger_inst.step_fail("STEP_5", ts, exc)
        raise


def step_image(
    episode_date: str, episode_id: str, ctx: dict, script_dict: dict, logger_inst
) -> list:
    """STEP 6: Gemini 이미지 생성."""
    ts = logger_inst.step_start("STEP_6", "Gemini 이미지 생성")
    try:
        from engine.image.gemini_client import generate_episode as gemini_generate
        from engine.image.prompt_builder import build_for_episode

        output_dir = Path("output") / "episodes" / episode_date / "panels"
        output_dir.mkdir(parents=True, exist_ok=True)

        panel_prompts = build_for_episode(script_dict)
        panels_input = [
            {
                "panel_idx": pp.panel_idx,
                "prompt_text": pp.prompt_text,
                "ref_image_paths": pp.ref_image_paths,
            }
            for pp in panel_prompts
        ]

        panel_paths, total_cost = gemini_generate(panels_input, output_dir)

        # episode_assets 업데이트 — patch 사용 (기존 script_json 등 보존)
        import os as _os

        from engine.persist.asset_writer import patch as asset_patch

        panels_json = [
            {"panel_idx": i + 1, "path": str(p) if p else None} for i, p in enumerate(panel_paths)
        ]
        asset_patch(
            episode_date,
            ctx["event_type"],
            {
                "panels_json": panels_json,
                "image_prompts_json": [
                    {"idx": pp.panel_idx, "prompt": pp.prompt_text} for pp in panel_prompts
                ],
                "gemini_cost_usd": total_cost,
                "status": "image_generated",
                # GitHub Actions run_id → resume_episode.yml 아티팩트 다운로드용
                "artifact_run_id": _os.environ.get("GITHUB_RUN_ID"),
            },
        )

        # 이미지 경로 로그 출력
        success_paths = [str(p) for p in panel_paths if p]
        fallback_count = sum(1 for p in panel_paths if not p)
        for i, p in enumerate(panel_paths, 1):
            if p:
                logger_inst.info("STEP_6", f"  P{i}: {p}")
            else:
                logger_inst.info("STEP_6", f"  P{i}: [text_card fallback]")

        # 이미지 경로 목록 파일 저장
        ep_dir = Path("output") / "episodes" / episode_date
        ep_dir.mkdir(parents=True, exist_ok=True)
        img_log_path = ep_dir / f"{episode_id}_images.json"
        img_log_path.write_text(
            __import__("json").dumps(
                {"episode_id": episode_id, "panels": panels_json, "cost_usd": total_cost},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        logger_inst.step_done(
            "STEP_6",
            ts,
            f"{len(success_paths)}개 이미지 생성 / {fallback_count}개 fallback"
            f" (cost=${total_cost:.4f}) | 로그: {img_log_path}",
        )
        return panel_paths
    except Exception as exc:
        logger_inst.step_fail("STEP_6", ts, exc)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="ICG 파이프라인 실행")
    parser.add_argument(
        "--stage",
        default="all",
        choices=["all", "data", "analysis", "narrative", "persist", "image"],
    )
    parser.add_argument("--date", default=None, help="대상 날짜 (YYYY-MM-DD, 기본: 오늘)")
    args = parser.parse_args()

    episode_date = args.date or _latest_date(args.stage)

    # StepLogger 초기화
    from engine.common.logger import StepLogger, get_run_id

    run_id = get_run_id(episode_date)
    output_dir = Path("output") / "episodes" / episode_date
    sl = StepLogger(run_id=run_id, episode_date=episode_date, output_dir=output_dir)

    sl.info(
        "PIPELINE", f"ICG 파이프라인 시작 run_id={run_id} date={episode_date} stage={args.stage}"
    )

    try:
        ctx: dict = {}
        script_dict: dict = {}
        episode_id = _make_episode_id(episode_date)

        if args.stage in ("all", "data"):
            step_data(episode_date, sl)

        if args.stage in ("all", "analysis"):
            ctx = step_analysis(episode_date, sl)

        # ── 중복 발행 방어 (Layer 3) ─────────────────────────────────────
        # narrative 이후 단계는 이미 published 된 에피소드면 차단.
        # FORCE_RUN=true 로 우회 가능.
        if args.stage in ("all", "narrative", "persist", "image"):
            import os as _os

            from engine.persist.asset_writer import get_current_status

            _force = _os.environ.get("FORCE_RUN", "false").lower() == "true"
            try:
                _cur = get_current_status(episode_date, "NORMAL")
                if _cur == "published" and not _force:
                    sl.error(
                        "PIPELINE",
                        f"🛑 이미 published 상태 — episode_date={episode_date} 재생성 차단. "
                        f"강제 재생성이 필요하면 FORCE_RUN=true 설정 후 재실행.",
                    )
                    sys.exit(1)
            except SystemExit:
                raise
            except Exception as _exc:
                sl.warning("PIPELINE", f"published 상태 체크 실패 (진행): {_exc}")

        if args.stage in ("all", "narrative"):
            if not ctx:
                raise RuntimeError("narrative 단계는 analysis 먼저 실행해야 합니다.")
            script_dict = step_narrative(episode_date, episode_id, ctx, sl)

        if args.stage in ("all", "persist"):
            if not ctx or not script_dict:
                raise RuntimeError("persist 단계는 narrative 먼저 실행해야 합니다.")
            step_persist(episode_date, episode_id, ctx, script_dict, sl)

        if args.stage in ("all", "image"):
            if not ctx or not script_dict:
                raise RuntimeError("image 단계는 narrative 먼저 실행해야 합니다.")
            step_image(episode_date, episode_id, ctx, script_dict, sl)

        sl.info("PIPELINE", f"완료 episode_id={episode_id}")

    except Exception as exc:
        sl.error("PIPELINE", f"파이프라인 실패: {exc}", exc=exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
