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

v2.0 변경사항 (2026-04-18):
  - step_analysis(): SCENARIO_V2_ENABLED flag 기반 Scenario × Outcome 분기 추가
    (NO_BATTLE / ALLIANCE / ONE_VS_ONE 3종 시나리오 + EndingTone 결정)
  - SCENARIO_V2_ENABLED=false (기본값): 기존 로직 100% 유지
  - SCENARIO_V2_ENABLED=true: v2.0 로직 적용
"""

from __future__ import annotations

import argparse
import logging
import os
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
    """STEP 3: 분석 + Battle → icg.daily_analysis. context dict 반환.

    v2.0 (SCENARIO_V2_ENABLED=true):
        3-1. 기존 1:1 캐릭터 선정 (기반값)
        3-2. risk_level 산출 (delta 기반 자체 계산)
        3-3. scenario 결정 (ONE_VS_ONE / NO_BATTLE / ALLIANCE)
        3-4. 캐릭터 재선정 (scenario별 분기)
        3-5. battle 계산 (scenario별 분기)
        3-6/7. outcome + ending_tone 결정
        3-8. ctx에 v2.0 필드 주입 + daily_analysis 별도 업데이트
    """
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

        # ── STEP 3-1: 기존 1:1 캐릭터 선정 (기반값, v2.0 분기 전) ─────────────
        hero_id_base, villain_id_base = select_characters_for_event(event_type, delta)

        # ── SCENARIO_V2 Feature Flag 확인 ─────────────────────────────────────
        _scenario_v2 = os.environ.get("SCENARIO_V2_ENABLED", "false").lower() == "true"

        # v2.0 작업 변수 초기값 (flag OFF 시 기존 로직 그대로)
        risk_level_v2    = "MEDIUM"
        scenario_type_v2 = "ONE_VS_ONE"
        ending_tone_v2   = "TENSE"
        heroes_v2: list[str] = [hero_id_base]
        hero_id   = hero_id_base
        villain_id = villain_id_base

        if _scenario_v2:
            # ── STEP 3-2: risk_level 산출 (delta 기반 자체 계산) ──────────────
            from engine.narrative.scenario_selector import compute_risk_level_from_delta
            risk_level_v2 = compute_risk_level_from_delta(delta)
            logger.info("[Step 3-2] risk_level=%s", risk_level_v2)

            # ── STEP 3-3: scenario 결정 ────────────────────────────────────────
            from engine.narrative.scenario_selector import select_scenario
            scenario_type_v2 = select_scenario(risk_level_v2, event_type)
            logger.info("[Step 3-3] scenario=%s", scenario_type_v2)

            # ── STEP 3-4: 캐릭터 재선정 (scenario별 분기) ─────────────────────
            if scenario_type_v2 == "NO_BATTLE":
                from engine.narrative.character_selector import select_for_no_battle
                hero_id, _no_villain = select_for_no_battle(delta)
                villain_id = villain_id_base  # analysis_upsert용 유지 (None 방어)
                heroes_v2  = [hero_id]
                logger.info("[Step 3-4] NO_BATTLE hero=%s", hero_id)

            elif scenario_type_v2 == "ALLIANCE":
                from engine.narrative.character_selector import select_for_alliance
                heroes_v2, villain_id = select_for_alliance(event_type, delta, villain_id_base)
                hero_id = heroes_v2[0]
                logger.info("[Step 3-4] ALLIANCE heroes=%s villain=%s", heroes_v2, villain_id)

            else:
                # ONE_VS_ONE — 기존 캐릭터 그대로
                hero_id    = hero_id_base
                villain_id = villain_id_base
                heroes_v2  = [hero_id]

        # ── characters.yaml base_power 로드 (공통) ─────────────────────────────
        canon = yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))
        try:
            from engine.common.notion_loader import load_battle_constants

            _bp_tbl = load_battle_constants().get("CHARACTER_BASE_POWER", {})
            hero_base = _bp_tbl.get(
                hero_id, canon["heroes"].get(hero_id, {}).get("base_power", 75)
            )
            villain_base = _bp_tbl.get(
                villain_id, canon["villains"].get(villain_id, {}).get("base_power", 72)
            )
        except Exception:
            hero_base    = canon["heroes"].get(hero_id, {}).get("base_power", 75)
            villain_base = canon["villains"].get(villain_id, {}).get("base_power", 72)

        market_ctx = get_market_context_for_battle(delta, curr_row)

        # ── STEP 3-5: battle 계산 (scenario별 분기) ───────────────────────────
        if _scenario_v2 and scenario_type_v2 == "NO_BATTLE":
            # 전투 없음 — 더미 BattleResult 생성 (analysis_upsert 시그니처 유지)
            from engine.narrative.battle_calc import BattleResult
            battle_result = BattleResult(
                hero_id=hero_id,
                villain_id=villain_id,   # 기존 villain_id_base 유지
                hero_power=0,
                villain_power=0,
                balance=0,
                outcome="PEACEFUL_GROWTH",
                hero_power_breakdown={},
                villain_power_breakdown={},
            )
            logger.info("[Step 3-5] NO_BATTLE → PEACEFUL_GROWTH (전투 스킵)")

        elif _scenario_v2 and scenario_type_v2 == "ALLIANCE":
            from engine.narrative.battle_calc import battle_alliance

            # 각 히어로 base_power 수집
            hero_bases: list[int] = []
            for h_id in heroes_v2:
                try:
                    from engine.common.notion_loader import load_battle_constants as _lbc
                    _bp = _lbc().get("CHARACTER_BASE_POWER", {})
                    hero_bases.append(
                        _bp.get(h_id, canon["heroes"].get(h_id, {}).get("base_power", 75))
                    )
                except Exception:
                    hero_bases.append(canon["heroes"].get(h_id, {}).get("base_power", 75))

            battle_result = battle_alliance(
                hero_ids=heroes_v2,
                hero_bases=hero_bases,
                villain_id=villain_id,
                villain_base=villain_base,
                market_context=market_ctx,
                arc_context=arc_context,
            )
            logger.info(
                "[Step 3-5] ALLIANCE balance=%d outcome=%s",
                battle_result.balance, battle_result.outcome,
            )

        else:
            # ONE_VS_ONE — 기존 로직 그대로
            battle_result = battle(
                hero_id=hero_id,
                hero_base=hero_base,
                villain_id=villain_id,
                villain_base=villain_base,
                market_context=market_ctx,
                arc_context=arc_context,
            )

        # ── STEP 3-6/7: outcome + ending_tone 결정 ────────────────────────────
        if _scenario_v2:
            from engine.narrative.scenario_selector import select_ending_tone
            ending_tone_v2 = select_ending_tone(
                scenario=scenario_type_v2,
                outcome=battle_result.outcome,
                risk_level=risk_level_v2,
            )
            logger.info(
                "[Step 3-6/7] outcome=%s ending_tone=%s",
                battle_result.outcome, ending_tone_v2,
            )

        # ── analysis_upsert (기존 시그니처 유지) ──────────────────────────────
        analysis_upsert(episode_date, event_type, battle_result.to_dict(), delta, arc_context)

        # ── STEP 3-8: v2.0 필드 daily_analysis 별도 업데이트 ─────────────────
        if _scenario_v2:
            try:
                from engine.common.supabase_client import icg_table
                icg_table("daily_analysis").update({
                    "scenario_type": scenario_type_v2,
                    "ending_tone":   ending_tone_v2,
                }).eq("analysis_date", episode_date).execute()
                logger.info(
                    "[Step 3-8] daily_analysis v2.0 업데이트 완료 "
                    "(scenario=%s tone=%s)",
                    scenario_type_v2, ending_tone_v2,
                )
            except Exception as _exc:
                logger.warning("[Step 3-8] v2.0 필드 DB 업데이트 실패 (진행): %s", _exc)

        # ── ctx 조립 ────────────────────────────────────────────────────────────
        ctx = {
            "event_type":   event_type,
            "delta":        delta,
            "battle_result": battle_result.to_dict(),
            "hero_id":      hero_id,
            "villain_id":   villain_id,
            "arc_context":  arc_context,
            # v2.0 신규 필드 (SCENARIO_V2_ENABLED=false 시 기본값 유지)
            "scenario_type": scenario_type_v2,
            "risk_level":    risk_level_v2,
            "ending_tone":   ending_tone_v2,
            "heroes":        heroes_v2,
        }

        # ── Hybrid 설계: ctx를 DB에 저장 (narrative/persist/image 독립 실행 대비) ──
        try:
            from engine.persist.asset_writer import save_analysis_ctx
            save_analysis_ctx(episode_date, event_type, ctx)
        except Exception as _exc:
            logger.warning("[step_analysis] ctx DB 저장 실패 (진행): %s", _exc)

        logger_inst.step_done(
            "STEP_3", ts,
            f"event={event_type} scenario={scenario_type_v2} "
            f"outcome={battle_result.outcome} tone={ending_tone_v2}",
        )
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
            # v2.0 신규 파라미터 (기존 generate_episode가 **kwargs 수용 시 자동 전달)
            scenario_type=ctx.get("scenario_type", "ONE_VS_ONE"),
            ending_tone=ctx.get("ending_tone", "TENSE"),
            heroes=ctx.get("heroes", [ctx["hero_id"]]),
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
                # v2.0 신규 필드 (episode_assets에 컬럼 추가됨)
                "scenario_type": ctx.get("scenario_type", "ONE_VS_ONE"),
                "heroes_json":   ctx.get("heroes", [ctx["hero_id"]]),
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
                "artifact_run_id": os.environ.get("GITHUB_RUN_ID"),
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

    _scenario_v2_log = os.environ.get("SCENARIO_V2_ENABLED", "false")
    sl.info(
        "PIPELINE",
        f"ICG 파이프라인 시작 run_id={run_id} date={episode_date} "
        f"stage={args.stage} SCENARIO_V2={_scenario_v2_log}",
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
        if args.stage in ("all", "narrative", "persist", "image"):
            _force = os.environ.get("FORCE_RUN", "false").lower() == "true"
            try:
                from engine.persist.asset_writer import get_current_status

                _cur = get_current_status(episode_date, "NORMAL")
                if _cur == "published" and not _force:
                    sl.error(
                        "PIPELINE",
                        f"🛑 이미 published 상태 — episode_date={episode_date} 재생성 차단. "
                        "강제 재생성이 필요하면 FORCE_RUN=true 설정 후 재실행.",
                    )
                    sys.exit(1)
            except SystemExit:
                raise
            except Exception as _exc:
                sl.warning("PIPELINE", f"published 상태 체크 실패 (진행): {_exc}")

        if args.stage in ("all", "narrative"):
            if not ctx:
                # ── Hybrid: 단독 실행 시 DB에서 ctx 복원 ────────────────
                from engine.persist.asset_writer import load_analysis_ctx
                ctx = load_analysis_ctx(episode_date)
                if not ctx:
                    raise RuntimeError(
                        f"narrative 단계 실행 불가 — episode_date={episode_date}의 "
                        "analysis_ctx_json 없음. analysis stage를 먼저 실행하세요."
                    )
                sl.info("STEP_4", f"[Hybrid] ctx DB 복원 완료 event_type={ctx.get('event_type')}")
            script_dict = step_narrative(episode_date, episode_id, ctx, sl)

            # ── Hybrid: script_dict를 DB에 저장 (persist/image 독립 실행 대비) ──
            try:
                from engine.persist.asset_writer import save_narrative_script
                save_narrative_script(episode_date, script_dict)
            except Exception as _exc:
                logger.warning("[step_narrative] script DB 저장 실패 (진행): %s", _exc)

        if args.stage in ("all", "persist"):
            if not ctx:
                from engine.persist.asset_writer import load_analysis_ctx
                ctx = load_analysis_ctx(episode_date)
                if not ctx:
                    raise RuntimeError(
                        "persist 단계 실행 불가 — analysis_ctx_json 없음. "
                        "analysis stage를 먼저 실행하세요."
                    )
            if not script_dict:
                from engine.persist.asset_writer import load_narrative_script
                script_dict = load_narrative_script(episode_date)
                if not script_dict:
                    raise RuntimeError(
                        "persist 단계 실행 불가 — script_json 없음. "
                        "narrative stage를 먼저 실행하세요."
                    )
                sl.info("STEP_5", "[Hybrid] narrative_script_json DB 복원 완료")
            step_persist(episode_date, episode_id, ctx, script_dict, sl)

        if args.stage in ("all", "image"):
            if not ctx:
                from engine.persist.asset_writer import load_analysis_ctx
                ctx = load_analysis_ctx(episode_date)
                if not ctx:
                    raise RuntimeError(
                        "image 단계 실행 불가 — analysis_ctx_json 없음. "
                        "analysis stage를 먼저 실행하세요."
                    )
            if not script_dict:
                from engine.persist.asset_writer import load_narrative_script
                script_dict = load_narrative_script(episode_date)
                if not script_dict:
                    raise RuntimeError(
                        "image 단계 실행 불가 — script_json 없음. "
                        "narrative stage를 먼저 실행하세요."
                    )
                sl.info("STEP_6", "[Hybrid] narrative_script_json DB 복원 완료")
            step_image(episode_date, episode_id, ctx, script_dict, sl)

        sl.info("PIPELINE", f"완료 episode_id={episode_id}")

    except Exception as exc:
        sl.error("PIPELINE", f"파이프라인 실패: {exc}", exc=exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
