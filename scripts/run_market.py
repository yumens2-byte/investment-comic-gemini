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

v1.29.1 (2026-04-22 — episode_id 불일치 + 로그 통일):
  - _make_episode_id(): 미발행 에피소드가 있으면 재사용 (별도 프로세스 실행 대응)
  - step_analysis() Step 3-Story: logger.info/warning → logger_inst.info/warning
    (run.log NDJSON 기록 보장, StepLogger 통일)
  - main() Step 3-Story-Save: logger.warning → sl.warning 통일

v1.29.0 (2026-04-22 — Step 3-Story 보정):
  - step_analysis(): SCENARIO_V2 분기 내부에 STEP 3-Story 블록 추가
    → engine.character.* 엔진 활성화 (character_engine/story_state_manager/prompt_builder)
    → ctx["guest_character_prompt"], ctx["_story_state"], ctx["_guest_characters"] 주입
  - step_narrative(): generate_episode 호출에 guest_character_prompt 전달
  - main(): persist 완료 후 _save_story_state() 호출로 다음 날 에피소드 상태 저장
  - Feature flag: 기존 SCENARIO_V2_ENABLED에 편입 (별도 STEP3_STORY_ENABLED 없음)
  - 후방 호환: SCENARIO_V2_ENABLED=false 시 ctx에 빈 값 주입, 기존 로직 그대로
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
    """
    에피소드 ID 생성/재사용 (ICG-YYYY-MM-DD-NNN).

    Hybrid 멀티-스테이지 패턴 대응:
      - 해당 날짜에 아직 published 되지 않은 에피소드가 있으면 → 해당 ID 재사용
      - 없으면 → (last_no + 1) 로 신규 생성
    이렇게 하지 않으면 image stage 등 후속 stage가 별도 프로세스로
    실행될 때 +1 증가한 ID를 반환하여 episode_id 불일치가 발생함.

    v1.29.1 (2026-04-22): episode_id 불일치 버그 수정.
    """
    from engine.common.supabase_client import icg_table

    try:
        rows = (
            icg_table("episode_assets")
            .select("episode_no, status")
            .eq("episode_date", episode_date)
            .order("episode_no", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            last_no = rows.data[0]["episode_no"] or 0
            last_status = rows.data[0].get("status") or ""
            # 진행 중인 에피소드 (미발행) → 재사용
            if last_status != "published":
                episode_id = f"ICG-{episode_date}-{last_no:03d}"
                logger.info(
                    "[pipeline] 기존 episode_id 재사용: %s (status=%s)",
                    episode_id,
                    last_status,
                )
                return episode_id
            # 마지막이 published → 새 번호 생성
            no = last_no + 1
        else:
            no = 1
    except Exception as _exc:
        logger.warning("[pipeline] episode_id 조회 실패 (no=1 fallback): %s", _exc)
        no = 1

    return f"ICG-{episode_date}-{no:03d}"


def _env_flag_enabled(name: str) -> bool:
    """Return True for boolean feature flags represented as strings."""
    return os.environ.get(name, "false").strip().lower() == "true"


_CONTINUITY_FLAG_NAMES = (
    "NARRATIVE_CONTEXT_ENABLED",
    "STORY_PLANNER_ENABLED",
    "CONTINUITY_STRICT_ENABLED",
    "ARC_STATE_V3_ENABLED",
    "EPISODE_TYPE_V3_ENABLED",
)


def _feature_flag_snapshot() -> dict[str, bool]:
    """Capture continuity-critical flags for cross-stage diagnostics."""
    return {name: _env_flag_enabled(name) for name in _CONTINUITY_FLAG_NAMES}


def _record_context_error(ctx: dict, feature: str, exc: Exception, *, strict: bool) -> None:
    """Attach recoverable context-generation errors to analysis_ctx_json."""
    ctx.setdefault("context_errors", []).append(
        {
            "feature": feature,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
            "strict": strict,
        }
    )


def _quality_gate_context(ctx: dict) -> str:
    flags = ctx.get("feature_flags_snapshot") or _feature_flag_snapshot()
    errors = ctx.get("context_errors") or []
    return (
        f" flags={flags}; context_errors={errors}; "
        "stage가 all이 아니면 analysis stage를 동일 flag로 재실행하세요."
    )


def _validate_narrative_quality_inputs(ctx: dict) -> dict[str, int | bool]:
    """Fail fast when enabled narrative-quality pilot inputs were lost between stages."""
    narrative_enabled = _env_flag_enabled("NARRATIVE_CONTEXT_ENABLED")
    planner_enabled = _env_flag_enabled("STORY_PLANNER_ENABLED")
    context_pack = ctx.get("narrative_context_pack") or {}
    story_plan = ctx.get("story_beat_plan") or {}

    if narrative_enabled and not context_pack:
        raise RuntimeError(
            "NARRATIVE_CONTEXT_ENABLED=true 이지만 analysis_ctx_json에 "
            "narrative_context_pack이 없습니다." + _quality_gate_context(ctx)
        )
    if planner_enabled and not story_plan:
        raise RuntimeError(
            "STORY_PLANNER_ENABLED=true 이지만 analysis_ctx_json에 story_beat_plan이 없습니다."
            + _quality_gate_context(ctx)
        )

    evidence_count = len(context_pack.get("top_evidence") or [])
    beat_count = len(story_plan.get("panel_beats") or [])
    if narrative_enabled and evidence_count == 0:
        raise RuntimeError(
            "Narrative Context Pack은 생성됐지만 top_evidence가 0개입니다. "
            "시장 데이터 품질을 확인하세요." + _quality_gate_context(ctx)
        )
    if planner_enabled and beat_count != 8:
        raise RuntimeError(
            f"Story Beat Plan panel_beats는 8개여야 합니다. 현재 {beat_count}개입니다."
            + _quality_gate_context(ctx)
        )

    return {
        "narrative_enabled": narrative_enabled,
        "planner_enabled": planner_enabled,
        "evidence_count": evidence_count,
        "beat_count": beat_count,
    }


def _ensure_narrative_quality_inputs(ctx: dict) -> dict:
    """Rebuild enabled narrative-quality inputs when a restored analysis ctx lacks them.

    Multi-stage GitHub Actions runs persist ``analysis_ctx_json`` in STEP 3 and restore it
    in STEP 4.  If pilot flags are enabled after STEP 3, or if STEP 3 saved a legacy ctx,
    the strict STEP 4 quality gate used to fail even though the core market data needed to
    build the pack is already present in ctx.  Rebuilding here keeps optional data gaps
    (for example crypto basis/social sentiment outages) from being misreported as missing
    required story inputs.
    """
    narrative_enabled = _env_flag_enabled("NARRATIVE_CONTEXT_ENABLED")
    planner_enabled = _env_flag_enabled("STORY_PLANNER_ENABLED")
    if not narrative_enabled and not planner_enabled:
        return ctx

    rebuilt_ctx = dict(ctx)
    if narrative_enabled and not rebuilt_ctx.get("narrative_context_pack"):
        from engine.analysis.story_context_builder import build_narrative_context_pack

        rebuilt_ctx["narrative_context_pack"] = build_narrative_context_pack(
            delta=rebuilt_ctx.get("delta") or {},
            battle_result=rebuilt_ctx.get("battle_result") or {},
            event_type=str(rebuilt_ctx.get("event_type") or "NORMAL"),
            scenario_type=str(rebuilt_ctx.get("scenario_type") or "ONE_VS_ONE"),
            ending_tone=str(rebuilt_ctx.get("ending_tone") or "TENSE"),
            arc_context=rebuilt_ctx.get("arc_context") or {},
            previous_episode=rebuilt_ctx.get("previous_episode"),
        )

    if planner_enabled and not rebuilt_ctx.get("story_beat_plan"):
        from engine.narrative.story_planner import build_story_beat_plan

        if not rebuilt_ctx.get("narrative_context_pack"):
            raise RuntimeError(
                "STORY_PLANNER_ENABLED=true 이지만 Story Beat Plan을 만들 "
                "narrative_context_pack이 없습니다."
            )
        hero_id = str(rebuilt_ctx.get("hero_id") or "")
        villain_id = str(rebuilt_ctx.get("villain_id") or "")
        rebuilt_ctx["story_beat_plan"] = build_story_beat_plan(
            narrative_context_pack=rebuilt_ctx["narrative_context_pack"],
            hero_id=hero_id,
            villain_id=villain_id,
            battle_result=rebuilt_ctx.get("battle_result") or {},
            scenario_type=str(rebuilt_ctx.get("scenario_type") or "ONE_VS_ONE"),
            hero_ids=rebuilt_ctx.get("heroes") or ([hero_id] if hero_id else []),
            villain_ids=rebuilt_ctx.get("villain_ids") or ([villain_id] if villain_id else []),
        ).model_dump()

    return rebuilt_ctx


def _build_continuity_repair_instructions(script_dict: dict, continuity_payload: dict) -> str:
    """Build a constrained one-shot repair prompt for strict continuity failures."""
    missing = continuity_payload.get("missing_requirements") or []
    warnings = continuity_payload.get("warnings") or []
    return (
        "Previous draft failed the strict continuity gate.\n"
        f"- continuity_score: {continuity_payload.get('total_score', 0):.1f}/100\n"
        f"- status: {continuity_payload.get('status', 'unknown')}\n"
        f"- previous_source_episode_id: "
        f"{continuity_payload.get('previous_source_episode_id') or 'unknown'}\n"
        f"- missing_requirements: {', '.join(missing) if missing else 'none'}\n"
        f"- warnings: {'; '.join(warnings) if warnings else 'none'}\n\n"
        "Revise only the narrative continuity payoff:\n"
        "1. Panel 1 or 2 must explicitly acknowledge the previous episode hook/thread.\n"
        "2. Preserve supplied market facts, event_type, battle_result, scenario_type, "
        "hero/villain IDs, and the 8-panel structure.\n"
        "3. Return the full EpisodeScript JSON only."
    )


def _load_recent_scenarios(episode_date: str, limit: int = 7) -> list[str]:
    """
    최근 에피소드 시나리오 타입 목록 조회.

    중복 방지용 참고 데이터로만 사용하므로, 실패 시 빈 리스트 반환(진행).
    """
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("episode_assets")
            .select("scenario_type")
            .lt("episode_date", episode_date)
            .order("episode_date", desc=True)
            .limit(limit)
            .execute()
        )
        return [str(r.get("scenario_type") or "").upper() for r in (rows.data or []) if r]
    except Exception as exc:
        logger.warning("[step_analysis] 최근 시나리오 조회 실패 (진행): %s", exc)
        return []


def _load_recent_outcomes(episode_date: str, limit: int = 3) -> list[str]:
    """
    최근 에피소드 battle_json.outcome 목록 조회.

    episode_type_engine CONFLICT 3-AND 조건 판정용.
    실패 시 빈 리스트 반환 (파이프라인 중단 안 함).
    """
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("episode_assets")
            .select("battle_json")
            .lt("episode_date", episode_date)
            .order("episode_date", desc=True)
            .limit(limit)
            .execute()
        )
        outcomes = []
        for r in rows.data or []:
            bj = r.get("battle_json") or {}
            outcome = bj.get("outcome") or ""
            if outcome:
                outcomes.append(str(outcome))
        return outcomes
    except Exception as exc:
        logger.warning("[step_analysis] 최근 outcome 조회 실패 (진행): %s", exc)
        return []


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
        from engine.data.snapshot_writer import (
            build_snapshot_payload,
            enforce_critical_quality,
            upsert,
        )

        fred = fred_fetcher.fetch_all(episode_date)
        market = market_fetcher.fetch_all(episode_date)
        fg = feargreed_fetcher.fetch_all(episode_date)
        crypto = crypto_fetcher.fetch_all(episode_date)
        sentiment = sentiment_fetcher.fetch_all(episode_date)

        extended_data: dict = {}
        if os.environ.get("MARKET_DATA_EXTENDED_ENABLED", "false").lower() == "true":
            try:
                from engine.data import sector_fetcher

                extended_data.update(
                    sector_fetcher.fetch_all(
                        episode_date,
                        spy_change=market.get("spy_change"),
                    )
                )
                logger_inst.info(
                    "STEP_2",
                    "[MarketDataExtended] sector_heatmap 수집 완료 "
                    f"coverage={extended_data.get('sector_heatmap', {}).get('coverage', 0):.0%}",
                )
            except Exception as _ext_exc:
                logger_inst.warning(
                    "STEP_2",
                    f"[MarketDataExtended] 확장 데이터 수집 실패 (파이프라인 계속): {_ext_exc}",
                )

        snapshot_payload = build_snapshot_payload(
            fred,
            market,
            fg,
            crypto,
            sentiment,
            extended_data or None,
        )

        if os.environ.get("CRITICAL_DATA_GATE_ENABLED", "true").lower() == "true":
            quality = enforce_critical_quality(
                snapshot_payload,
                context=f"STEP_2 date={episode_date}",
            )
            logger_inst.info(
                "STEP_2",
                "[CriticalDataGate] 통과 "
                f"missing={len(quality['missing'])} optional={len(quality['optional_missing'])}",
            )
        else:
            logger_inst.warning("STEP_2", "[CriticalDataGate] 비활성화 — 운영 override 적용")

        upsert(episode_date, fred, market, fg, crypto, sentiment, extended_data or None)

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

        signal_pack: dict | None = None
        risk_trace_v3: dict | None = None
        if os.environ.get("SIGNAL_PACK_V1_ENABLED", "false").lower() == "true":
            try:
                from engine.analysis.signal_pack_builder import build_signal_pack

                signal_pack = build_signal_pack(delta, curr_row)
                logger_inst.info(
                    "STEP_3",
                    "[SignalPack] 생성 완료 "
                    f"signals={len(signal_pack.get('signals', []))} "
                    f"confidence={signal_pack.get('data_confidence', 0):.2f}",
                )
            except Exception as _sig_exc:
                logger_inst.warning(
                    "STEP_3",
                    f"[SignalPack] 생성 실패 (파이프라인 계속): {_sig_exc}",
                )
                signal_pack = None

        if (
            signal_pack is not None
            and os.environ.get("RISK_SCORE_V3_ENABLED", "false").lower() == "true"
        ):
            try:
                from engine.analysis.risk_score_engine import compute as compute_risk_score

                risk_trace_v3 = compute_risk_score(signal_pack)
                logger_inst.info(
                    "STEP_3",
                    "[RiskScoreV3] "
                    f"risk={risk_trace_v3.get('risk_level')} "
                    f"score={risk_trace_v3.get('risk_score', 0):.2f} "
                    f"dominant={risk_trace_v3.get('dominant_domain')}",
                )
            except Exception as _risk_exc:
                logger_inst.warning(
                    "STEP_3",
                    f"[RiskScoreV3] 계산 실패 (legacy risk 유지): {_risk_exc}",
                )
                risk_trace_v3 = None

        # -- ARC_STATE_V3: arc_context 동적 로드 (2026-05-02) ----------------
        _arc_v3 = os.environ.get("ARC_STATE_V3_ENABLED", "false").lower() == "true"
        if _arc_v3:
            from engine.arc.arc_state_engine import build_arc_context as _build_arc_ctx
            from engine.arc.arc_state_engine import load_arc_state

            _arc_state_loaded = load_arc_state()
            arc_context = _build_arc_ctx(_arc_state_loaded)
            logger.info(
                "[Step 3-ARC_V3] arc_context 로드 (tension=%d arc_day=%d sig=%d crowd=%d)",
                arc_context["tension"],
                arc_context["days_since_last"],
                arc_context["villain_signature"],
                arc_context["crowd_momentum"],
            )
        else:
            _arc_state_loaded = None
            arc_context = {"tension": 40, "days_since_last": 0, "yesterday_type": "NORMAL"}

        event_type = classify(delta, arc_context)

        # ── STEP 3-1: 기존 1:1 캐릭터 선정 (기반값, v2.0 분기 전) ─────────────
        hero_id_base, villain_id_base = select_characters_for_event(event_type, delta)

        # ── SCENARIO_V2 Feature Flag 확인 ─────────────────────────────────────
        _scenario_v2 = os.environ.get("SCENARIO_V2_ENABLED", "false").lower() == "true"

        # v2.0 작업 변수 초기값 (flag OFF 시 기존 로직 그대로)
        risk_level_v2 = "MEDIUM"
        scenario_type_v2 = "ONE_VS_ONE"
        ending_tone_v2 = "TENSE"
        heroes_v2: list[str] = [hero_id_base]
        villain_ids_v2: list[str] = [villain_id_base]
        character_selection_trace: dict = {}
        hero_id = hero_id_base
        villain_id = villain_id_base
        # ARC_STATE_V3 + EPISODE_TYPE_V3 초기값 (2026-05-02)
        _episode_type_v3: str | None = None
        _form_bonus_v3: int = 0

        if _scenario_v2:
            # ── STEP 3-2: risk_level 산출 (delta 기반 자체 계산) ──────────────
            from engine.narrative.scenario_selector import compute_risk_level_from_delta

            risk_level_v2 = (
                str(risk_trace_v3.get("risk_level"))
                if risk_trace_v3 is not None and risk_trace_v3.get("risk_level")
                else compute_risk_level_from_delta(delta)
            )
            logger.info("[Step 3-2] risk_level=%s", risk_level_v2)

            # ── STEP 3-3: scenario 결정 ────────────────────────────────────────
            from engine.narrative.scenario_selector import select_scenario

            scenario_type_v2 = select_scenario(risk_level_v2, event_type)
            logger.info("[Step 3-3] scenario=%s", scenario_type_v2)

            # ── STEP 3-3b: 스토리라인 중복 완화 (최근 시나리오 연속 반복 방지) ──
            from engine.narrative.storyline_guard import choose_scenario_with_diversity

            recent_scenarios = _load_recent_scenarios(episode_date, limit=7)
            scenario_type_v2, diversity_reason = choose_scenario_with_diversity(
                base_scenario=scenario_type_v2,
                risk_level=risk_level_v2,
                event_type=event_type,
                recent_scenarios=recent_scenarios,
                max_same_streak=2,
            )
            logger.info(
                "[Step 3-3b] scenario_diversity scenario=%s recent=%s reason=%s",
                scenario_type_v2,
                recent_scenarios[:5],
                diversity_reason,
            )

            # -- STEP 3-3c: EPISODE_TYPE_V3 결정 (2026-05-02) ----------------
            _ep_v3 = os.environ.get("EPISODE_TYPE_V3_ENABLED", "false").lower() == "true"
            # ARC_STATE_V3 데이터 없으면 episode_type_engine 스킵 (arc_day=0 오판정 방지)
            if _ep_v3 and _arc_state_loaded is not None:
                try:
                    from engine.narrative.episode_type_engine import (
                        determine_episode_type as _det_ep_type,
                    )

                    _prev_villain = (_arc_state_loaded or {}).get("active_villain", "")
                    _villain_changed = _prev_villain != "" and _prev_villain != villain_id_base
                    _recent_outcomes = _load_recent_outcomes(episode_date, limit=3)
                    _ep_result = _det_ep_type(
                        arc_state=_arc_state_loaded or {},
                        delta=delta,
                        risk_level=risk_level_v2,
                        recent_outcomes=_recent_outcomes,
                        villain_changed=_villain_changed,
                    )
                    _episode_type_v3 = _ep_result.episode_type
                    _form_bonus_v3 = _ep_result.form_bonus
                    # scenario_type_v2를 역변환값으로 덮어씀 (기존 분기 호환)
                    scenario_type_v2 = _ep_result.scenario_type
                    logger.info(
                        "[Step 3-3c] episode_type_v3=%s scenario=%s form_bonus=%d",
                        _episode_type_v3,
                        scenario_type_v2,
                        _form_bonus_v3,
                    )
                except Exception as _ep_exc:
                    logger.warning("[Step 3-3c] episode_type_v3 판정 실패 (진행): %s", _ep_exc)

            # -- STEP 3-4: 캐릭터 재선정 (scenario별 분기) --------------------
            if scenario_type_v2 == "NO_BATTLE":
                from engine.narrative.character_selector import select_for_no_battle

                hero_id, _no_villain = select_for_no_battle(delta)
                villain_id = villain_id_base  # analysis_upsert용 유지 (None 방어)
                heroes_v2 = [hero_id]
                villain_ids_v2 = []
                logger.info("[Step 3-4] NO_BATTLE hero=%s", hero_id)

            elif scenario_type_v2 == "ALLIANCE":
                from engine.narrative.character_selector import select_for_alliance

                heroes_v2, villain_id = select_for_alliance(event_type, delta, villain_id_base)
                villain_ids_v2 = [villain_id]
                hero_id = heroes_v2[0]
                logger.info("[Step 3-4] ALLIANCE heroes=%s villain=%s", heroes_v2, villain_id)

            else:
                # ONE_VS_ONE — 기존 캐릭터 그대로
                hero_id = hero_id_base
                villain_id = villain_id_base
                villain_ids_v2 = [villain_id]
                heroes_v2 = [hero_id]

            # -- STEP 3-4b: Character Appearance v2 점수 기반 재선정 ----------
            if os.environ.get("CHARACTER_APPEARANCE_V2_ENABLED", "false").lower() == "true":
                try:
                    from engine.narrative.character_appearance_engine import (
                        resolve_character_selection,
                    )

                    _selection = resolve_character_selection(
                        delta=delta,
                        event_type=event_type,
                        scenario_type=scenario_type_v2,
                        risk_level=risk_level_v2,
                        base_hero_id=hero_id_base,
                        base_villain_id=villain_id_base,
                        arc_context=arc_context,
                        curr_row=curr_row,
                        recent_outcomes=_load_recent_outcomes(episode_date, limit=3),
                    )
                    character_selection_trace = _selection.to_dict()
                    hero_id = _selection.primary_hero
                    heroes_v2 = _selection.heroes
                    if scenario_type_v2 == "NO_BATTLE":
                        # legacy persistence compatibility: battle_json still carries a villain_id,
                        # while character_selection.primary_villain explicitly records None.
                        villain_id = villain_id_base
                        villain_ids_v2 = []
                    else:
                        villain_id = _selection.primary_villain or villain_id_base
                        villain_ids_v2 = _selection.villains or [villain_id]
                    logger.info(
                        "[Step 3-4b] character_appearance_v2 hero=%s heroes=%s villain=%s reason=%s",
                        hero_id,
                        heroes_v2,
                        villain_id,
                        _selection.selection_reason,
                    )
                except Exception as _sel_exc:
                    logger.warning(
                        "[Step 3-4b] character_appearance_v2 실패 (기존 선택 유지): %s",
                        _sel_exc,
                    )

        # ── characters.yaml base_power 로드 (공통) ─────────────────────────────
        canon = yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))
        try:
            from engine.common.notion_loader import load_battle_constants

            _bp_tbl = load_battle_constants().get("CHARACTER_BASE_POWER", {})
            hero_base = _bp_tbl.get(hero_id, canon["heroes"].get(hero_id, {}).get("base_power", 75))
            villain_base = _bp_tbl.get(
                villain_id, canon["villains"].get(villain_id, {}).get("base_power", 72)
            )
        except Exception:
            hero_base = canon["heroes"].get(hero_id, {}).get("base_power", 75)
            villain_base = canon["villains"].get(villain_id, {}).get("base_power", 72)

        market_ctx = get_market_context_for_battle(delta, curr_row)

        # ── STEP 3-5: battle 계산 (scenario별 분기) ───────────────────────────
        if _scenario_v2 and scenario_type_v2 == "NO_BATTLE":
            # 전투 없음 — 더미 BattleResult 생성 (analysis_upsert 시그니처 유지)
            from engine.narrative.battle_calc import BattleResult

            battle_result = BattleResult(
                hero_id=hero_id,
                villain_id=villain_id,  # 기존 villain_id_base 유지
                hero_power=0,
                villain_power=0,
                balance=0,
                outcome="PEACEFUL_GROWTH",
                hero_power_breakdown={},
                villain_power_breakdown={},
            )
            logger.info("[Step 3-5] NO_BATTLE → PEACEFUL_GROWTH (전투 스킵)")

        elif _scenario_v2 and scenario_type_v2 == "ALLIANCE":
            from engine.narrative.battle_calc import battle_alliance, battle_multi_villain

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

            if len(villain_ids_v2) > 1:
                villain_bases = [
                    canon["villains"].get(v_id, {}).get("base_power", 72) for v_id in villain_ids_v2
                ]
                battle_result = battle_multi_villain(
                    hero_ids=heroes_v2,
                    hero_bases=hero_bases,
                    villain_ids=villain_ids_v2,
                    villain_bases=villain_bases,
                    market_context=market_ctx,
                    arc_context=arc_context,
                )
            else:
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
                battle_result.balance,
                battle_result.outcome,
            )

        else:
            # ONE_VS_ONE — 기존 로직 그대로
            # ARC_STATE_V3: form_bonus를 arc_context에 주입 (battle_calc T3 연동 준비)
            if _form_bonus_v3:
                arc_context = {**arc_context, "form_bonus": _form_bonus_v3}
            battle_result = battle(
                hero_id=hero_id,
                hero_base=hero_base,
                villain_id=villain_id,
                villain_base=villain_base,
                market_context=market_ctx,
                arc_context=arc_context,
                form_bonus=(
                    _form_bonus_v3
                    if os.environ.get("FORM_BONUS_PIPELINE_ENABLED", "false").lower() == "true"
                    else 0
                ),
            )

        # ── STEP 3-5b: Phase 2.3 Battle Modifier 파이프라인 연결 ─────────────
        if (
            os.environ.get("BATTLE_V23_PIPELINE_ENABLED", "false").lower() == "true"
            and scenario_type_v2 != "NO_BATTLE"
        ):
            try:
                from engine.narrative.battle_calc import apply_v23_modifiers

                _episode_for_modifier = _episode_type_v3 or event_type
                before_balance = battle_result.balance
                battle_result = apply_v23_modifiers(
                    battle_result, arc_context, _episode_for_modifier
                )
                logger.info(
                    "[Step 3-5b] battle_v23 modifiers episode=%s balance=%d→%d outcome=%s",
                    _episode_for_modifier,
                    before_balance,
                    battle_result.balance,
                    battle_result.outcome,
                )
            except Exception as _mod_exc:
                logger.warning("[Step 3-5b] battle_v23 modifier 실패 (원본 유지): %s", _mod_exc)

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
                battle_result.outcome,
                ending_tone_v2,
            )

        # ── analysis_upsert (기존 시그니처 유지 + v3 관측성 옵션) ─────────────
        _sector_rank: list[dict] | None = None
        _watch_areas: list[str] | None = None
        _caution_areas: list[str] | None = None
        if signal_pack is not None:
            _sector_signals = signal_pack.get("by_domain", {}).get("sector", [])
            _ranked_sectors = sorted(
                [s for s in _sector_signals if s.get("change_pct") is not None],
                key=lambda s: float(s.get("change_pct") or 0),
                reverse=True,
            )
            if _ranked_sectors:
                _sector_rank = [
                    {
                        "symbol": s.get("symbol"),
                        "name": s.get("name"),
                        "change_pct": s.get("change_pct"),
                        "relative_pct": s.get("relative_pct"),
                        "state": s.get("state"),
                    }
                    for s in _ranked_sectors
                ]
                _watch_areas = [str(s.get("name") or s.get("symbol")) for s in _ranked_sectors[:3]]
                _caution_areas = [
                    str(s.get("name") or s.get("symbol"))
                    for s in list(reversed(_ranked_sectors[-3:]))
                ]

        analysis_upsert(
            episode_date,
            event_type,
            battle_result.to_dict(),
            delta,
            arc_context,
            formula_trace=risk_trace_v3,
            risk_drivers=(risk_trace_v3 or {}).get("risk_drivers") if risk_trace_v3 else None,
            sector_rank=_sector_rank,
            watch_areas=_watch_areas,
            caution_areas=_caution_areas,
        )

        # ── STEP 3-Story: 게스트 캐릭터 판단 (2026-04-22 보정) ─────────────────
        # SCENARIO_V2_ENABLED=true 일 때만 실행. engine.character.* 엔진 활성화.
        # 실패해도 파이프라인은 계속 (try/except로 격리).
        _guest_prompt: str = ""
        _story_state: dict = {}
        _guest_characters: list = []
        if _scenario_v2:
            try:
                from engine.character.character_engine import resolve_guest_characters
                from engine.character.prompt_builder import build_guest_character_prompt
                from engine.character.story_state_manager import load_story_state

                _story_state = load_story_state(episode_date)
                _guest_characters = resolve_guest_characters(curr_row, _story_state)
                _guest_prompt = build_guest_character_prompt(
                    curr_row, _story_state, _guest_characters
                )
                # sl 사용 → run.log NDJSON 기록 보장 (logger.info는 StepLogger 미기록)
                if os.environ.get(
                    "NEUTRAL_GUEST_SCORING_ENABLED", "false"
                ).lower() == "true" and character_selection_trace.get("neutral_guests"):
                    _guest_characters = [
                        (g["char_id"], g["role"])
                        for g in character_selection_trace.get("neutral_guests", [])
                        if g.get("appear")
                    ]
                    _guest_prompt = build_guest_character_prompt(
                        curr_row, _story_state, _guest_characters
                    )
                _guest_names = [f"{c}({r})" for c, r in _guest_characters] or ["없음"]
                logger_inst.info(
                    "STEP_3",
                    f"[Step 3-Story] 게스트 {len(_guest_characters)}명: {_guest_names}",
                )
            except Exception as _exc:
                logger_inst.warning(
                    "STEP_3",
                    f"[Step 3-Story] 실패 (파이프라인 계속): {_exc}",
                )
                _guest_prompt, _story_state, _guest_characters = "", {}, []

        # ── STEP 3-8: v2.0 필드 daily_analysis 별도 업데이트 ─────────────────
        if _scenario_v2:
            try:
                from engine.common.supabase_client import icg_table

                _da_payload: dict = {
                    "scenario_type": scenario_type_v2,
                    "ending_tone": ending_tone_v2,
                }
                if _episode_type_v3:
                    _da_payload["episode_type_v3"] = _episode_type_v3
                icg_table("daily_analysis").update(_da_payload).eq(
                    "analysis_date", episode_date
                ).execute()
                logger.info(
                    "[Step 3-8] daily_analysis v2.0 업데이트 완료 (scenario=%s tone=%s)",
                    scenario_type_v2,
                    ending_tone_v2,
                )
            except Exception as _exc:
                logger.warning("[Step 3-8] v2.0 필드 DB 업데이트 실패 (진행): %s", _exc)

        if (
            not character_selection_trace
            and os.environ.get("CHARACTER_RULE_TRACE_ENABLED", "true").lower() == "true"
        ):
            character_selection_trace = {
                "version": "legacy-trace",
                "scenario_type": scenario_type_v2,
                "event_type": event_type,
                "risk_level": risk_level_v2,
                "primary_hero": hero_id,
                "support_heroes": [h for h in heroes_v2 if h != hero_id],
                "heroes": heroes_v2,
                "primary_villain": None if scenario_type_v2 == "NO_BATTLE" else villain_id,
                "support_villains": [v for v in villain_ids_v2 if v != villain_id],
                "villains": villain_ids_v2,
                "villain_roles": (
                    {}
                    if scenario_type_v2 == "NO_BATTLE"
                    else {
                        **({villain_id: "PRIMARY_THREAT"} if villain_id else {}),
                        **{v: "SECONDARY_THREAT" for v in villain_ids_v2 if v != villain_id},
                    }
                ),
                "neutral_guests": [
                    {"char_id": c, "role": r, "faction": "NEUTRAL", "appear": True}
                    for c, r in _guest_characters
                ],
                "selection_reason": (
                    "legacy selector trace; enable CHARACTER_APPEARANCE_V2_ENABLED "
                    "for scored candidate breakdown"
                ),
            }

        # ── ctx 조립 ────────────────────────────────────────────────────────────
        ctx = {
            "event_type": event_type,
            "delta": delta,
            "battle_result": battle_result.to_dict(),
            "hero_id": hero_id,
            "villain_id": villain_id,
            "villain_ids": villain_ids_v2,
            "arc_context": arc_context,
            # v2.0 신규 필드 (SCENARIO_V2_ENABLED=false 시 기본값 유지)
            "scenario_type": scenario_type_v2,
            "risk_level": risk_level_v2,
            "ending_tone": ending_tone_v2,
            "heroes": heroes_v2,
            # Step 3-Story 신규 필드 (2026-04-22 보정)
            "guest_character_prompt": _guest_prompt,
            "_story_state": _story_state,
            "_guest_characters": _guest_characters,
            # ARC_STATE_V3 신규 필드 (2026-05-02)
            "_arc_state": _arc_state_loaded,
            "_snapshot_row": curr_row,
            # EPISODE_TYPE_V3 신규 필드 (2026-05-02)
            "episode_type_v3": _episode_type_v3,
            "form_bonus": _form_bonus_v3,
            "character_selection": character_selection_trace,
            "signal_pack": signal_pack,
            "risk_trace_v3": risk_trace_v3,
        }

        ctx["feature_flags_snapshot"] = _feature_flag_snapshot()

        if os.environ.get("CHARACTER_CANON_PROMPT_V2_ENABLED", "false").lower() == "true":
            try:
                from engine.narrative.prompt_tpl import build_active_character_cards

                ctx["active_character_cards"] = build_active_character_cards(
                    canon=canon,
                    hero_ids=heroes_v2,
                    villain_id=(None if scenario_type_v2 == "NO_BATTLE" else villain_id),
                    villain_ids=villain_ids_v2,
                    neutral_guest_ids=[c for c, _ in _guest_characters][
                        : (1 if len(villain_ids_v2) > 1 else None)
                    ],
                )
            except Exception as _card_exc:
                logger.warning(
                    "[step_analysis] active character cards 생성 실패 (진행): %s", _card_exc
                )

        # ── Narrative Context Pilot: 데이터/스토리 고도화 컨텍스트 생성 ─────────
        if os.environ.get("NARRATIVE_CONTEXT_ENABLED", "false").lower() == "true":
            try:
                from engine.analysis.story_context_builder import (
                    build_narrative_context_pack,
                )
                from engine.narrative.continuity import (
                    detect_arc_pivot,
                    load_continuity_window,
                    load_previous_continuity,
                )

                _extended_context = (
                    os.environ.get("STORY_CONTEXT_EXTENDED_ENABLED", "false").lower() == "true"
                )
                _continuity_window = load_continuity_window(episode_date)
                ctx["continuity_window"] = _continuity_window
                _previous_episode = _continuity_window.get(
                    "primary_previous"
                ) or load_previous_continuity(episode_date)
                _arc_pivot = detect_arc_pivot(_previous_episode, arc_context)
                ctx["arc_pivot"] = _arc_pivot
                if _previous_episode:
                    ctx["previous_episode"] = _previous_episode
                    logger_inst.info(
                        "STEP_3",
                        "[Continuity] previous_episode=%s hook=%s"
                        % (
                            _previous_episode.get("source_episode_id"),
                            bool(_previous_episode.get("next_hook")),
                        ),
                    )
                _context_pack = build_narrative_context_pack(
                    delta=delta,
                    battle_result=battle_result.to_dict(),
                    event_type=event_type,
                    scenario_type=scenario_type_v2,
                    ending_tone=ending_tone_v2,
                    arc_context=arc_context,
                    previous_episode=_previous_episode,
                    news_items=(curr_row.get("news_items") if _extended_context else None),
                    economic_events=(curr_row.get("event_calendar") if _extended_context else None),
                    sector_heatmap=(curr_row.get("sector_heatmap") if _extended_context else None),
                )
                if _continuity_window.get("recent_threads"):
                    _context_pack["continuity_window"] = _continuity_window
                if _arc_pivot.get("pivot_required"):
                    _context_pack["arc_pivot"] = _arc_pivot
                    _context_pack.setdefault("continuity_directives", []).append(
                        _arc_pivot["instruction"]
                    )
                ctx["narrative_context_pack"] = _context_pack

                if os.environ.get("STORY_PLANNER_ENABLED", "false").lower() == "true":
                    from engine.narrative.story_planner import build_story_beat_plan

                    ctx["story_beat_plan"] = build_story_beat_plan(
                        narrative_context_pack=_context_pack,
                        hero_id=hero_id,
                        villain_id=villain_id,
                        battle_result=battle_result.to_dict(),
                        scenario_type=scenario_type_v2,
                        hero_ids=heroes_v2,
                        villain_ids=villain_ids_v2,
                    ).model_dump()
                logger_inst.info(
                    "STEP_3",
                    "[NarrativeContext] context_pack 생성 완료 "
                    f"evidence={len(_context_pack.get('top_evidence', []))} "
                    f"planner={'story_beat_plan' in ctx}",
                )
            except Exception as _ctx_exc:
                _record_context_error(
                    ctx,
                    "narrative_context_pack",
                    _ctx_exc,
                    strict=_env_flag_enabled("CONTINUITY_STRICT_ENABLED")
                    or _env_flag_enabled("NARRATIVE_CONTEXT_ENABLED")
                    or _env_flag_enabled("STORY_PLANNER_ENABLED"),
                )
                logger_inst.warning(
                    "STEP_3",
                    f"[NarrativeContext] 생성 실패 (파이프라인 계속): {_ctx_exc}",
                )

        # ── Hybrid 설계: ctx를 DB에 저장 (narrative/persist/image 독립 실행 대비) ──
        try:
            from engine.persist.asset_writer import save_analysis_ctx

            save_analysis_ctx(episode_date, event_type, ctx)
        except Exception as _exc:
            logger.warning("[step_analysis] ctx DB 저장 실패 (진행): %s", _exc)

        logger_inst.step_done(
            "STEP_3",
            ts,
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

        ctx = _ensure_narrative_quality_inputs(ctx)
        quality = _validate_narrative_quality_inputs(ctx)
        logger_inst.info(
            "STEP_4",
            "[QualityGate] narrative_context=%s evidence=%d story_planner=%s beats=%d"
            % (
                quality["narrative_enabled"],
                quality["evidence_count"],
                quality["planner_enabled"],
                quality["beat_count"],
            ),
        )

        generation_kwargs = {
            "date": episode_date,
            "episode_id": episode_id,
            "event_type": ctx["event_type"],
            "delta": ctx["delta"],
            "battle_result": ctx["battle_result"],
            "hero_id": ctx["hero_id"],
            "villain_id": ctx["villain_id"],
            "arc_context": ctx["arc_context"],
            # v2.0 신규 파라미터 (기존 generate_episode가 **kwargs 수용 시 자동 전달)
            "scenario_type": ctx.get("scenario_type", "ONE_VS_ONE"),
            "ending_tone": ctx.get("ending_tone", "TENSE"),
            "heroes": ctx.get("heroes", [ctx["hero_id"]]),
            # Step 3-Story 신규 파라미터 (2026-04-22 보정)
            "guest_character_prompt": ctx.get("guest_character_prompt", ""),
            # Narrative Context Pilot (2026-06-01)
            "narrative_context_pack": ctx.get("narrative_context_pack"),
            "story_beat_plan": ctx.get("story_beat_plan"),
            "active_character_cards": ctx.get("active_character_cards"),
            "villain_ids": ctx.get("villain_ids"),
        }
        script = generate_episode(**generation_kwargs)
        script_dict = script.model_dump()

        from engine.narrative.story_quality import (
            StoryContinuityError,
            build_continuity_quality_payload,
            validate_story_continuity,
            validate_story_grounding,
        )

        grounding_warnings = validate_story_grounding(
            script_dict,
            ctx.get("narrative_context_pack"),
            strict=_env_flag_enabled("NARRATIVE_CONTEXT_ENABLED"),
        )
        for warning in grounding_warnings:
            logger_inst.warning("STEP_4", f"[StoryGrounding] {warning}")

        strict_continuity = _env_flag_enabled("CONTINUITY_STRICT_ENABLED")
        script_dict["_continuity_quality"] = build_continuity_quality_payload(
            script_dict,
            ctx.get("narrative_context_pack"),
            ctx.get("story_beat_plan"),
            strict_enabled=strict_continuity,
        )
        try:
            continuity_warnings = validate_story_continuity(
                script_dict,
                ctx.get("narrative_context_pack"),
                ctx.get("story_beat_plan"),
                strict=strict_continuity,
            )
        except StoryContinuityError as continuity_exc:
            repair_instructions = _build_continuity_repair_instructions(
                script_dict,
                script_dict.get("_continuity_quality") or {},
            )
            logger_inst.warning(
                "STEP_4",
                "[StoryContinuity] strict gate failed; retrying one continuity repair: "
                f"{continuity_exc}",
            )
            repaired_script = generate_episode(
                **generation_kwargs,
                continuity_repair_instructions=repair_instructions,
            )
            script = repaired_script
            script_dict = repaired_script.model_dump()
            script_dict["_continuity_quality"] = build_continuity_quality_payload(
                script_dict,
                ctx.get("narrative_context_pack"),
                ctx.get("story_beat_plan"),
                strict_enabled=strict_continuity,
            )
            script_dict["_continuity_quality"]["repair_attempted"] = True
            script_dict["_continuity_quality"]["repair_reason"] = str(continuity_exc)
            continuity_warnings = validate_story_continuity(
                script_dict,
                ctx.get("narrative_context_pack"),
                ctx.get("story_beat_plan"),
                strict=strict_continuity,
            )
        else:
            script_dict["_continuity_quality"]["repair_attempted"] = False
        logger_inst.info(
            "STEP_4",
            "[StoryContinuity] previous=%s score=%.1f status=%s strict=%s warnings=%d"
            % (
                script_dict["_continuity_quality"].get("previous_source_episode_id"),
                script_dict["_continuity_quality"].get("total_score", 0),
                script_dict["_continuity_quality"].get("status"),
                strict_continuity,
                len(continuity_warnings),
            ),
        )
        for warning in continuity_warnings:
            logger_inst.warning("STEP_4", f"[StoryContinuity] {warning}")

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


def _build_episode_asset_payload(episode_id: str, ctx: dict, script_dict: dict) -> dict:
    """Build episode_assets payload with optional character selection snapshots."""
    script_for_asset = dict(script_dict)
    try:
        from engine.narrative.continuity import build_continuity_bundle

        script_for_asset["_continuity"] = build_continuity_bundle(
            episode_id,
            str(script_dict.get("date") or episode_id[4:14]),
            ctx,
            script_dict,
        )
        if script_dict.get("_continuity_quality"):
            script_for_asset["_continuity_quality"] = script_dict["_continuity_quality"]
    except Exception as _cont_exc:
        logger.warning("[step_persist] continuity bundle 생성 실패 (진행): %s", _cont_exc)

    payload = {
        "episode_no": int(episode_id.split("-")[-1]),
        "title": script_dict.get("title", ""),
        "script_json": script_for_asset,
        "battle_json": ctx["battle_result"],
        "status": "narrative_done",
        "scenario_type": ctx.get("scenario_type", "ONE_VS_ONE"),
        "heroes_json": ctx.get("heroes", [ctx["hero_id"]]),
    }
    if os.environ.get("CHARACTER_SELECTION_ASSET_SNAPSHOT_ENABLED", "false").lower() == "true":
        payload["character_selection_json"] = ctx.get("character_selection", {})
        payload["active_character_cards_json"] = ctx.get("active_character_cards", [])
    return payload


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
            _build_episode_asset_payload(episode_id, ctx, script_dict),
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

            # ── Step 3-Story-Save: 에피소드 완료 후 story_state 저장 (2026-04-22 보정) ──
            # SCENARIO_V2_ENABLED=true 이고 ctx에 _story_state 있을 때만 실행.
            # 실패해도 파이프라인 계속 (다음 날 load_story_state가 DEFAULT 반환).
            _scenario_v2_enabled = os.environ.get("SCENARIO_V2_ENABLED", "false").lower() == "true"
            if _scenario_v2_enabled and ctx.get("_story_state"):
                try:
                    from engine.character.story_state_manager import (
                        save_story_state,
                        update_after_episode,
                    )

                    _delta = ctx.get("delta") or {}
                    _vix = _delta.get("vix") or 0.0
                    _outcome = (ctx.get("battle_result") or {}).get("outcome", "DRAW")
                    _updated_state = update_after_episode(
                        ctx["_story_state"],
                        ctx.get("_guest_characters", []),
                        _outcome,
                        _vix,
                    )
                    save_story_state(episode_date, _updated_state)
                    sl.info(
                        "STEP_5",
                        f"[Step 3-Story-Save] story_state 저장 완료 "
                        f"(arc={_updated_state.get('arc_id')} "
                        f"ep={_updated_state.get('arc_episode', 0)} "
                        f"rift={_updated_state.get('world_state', {}).get('dimensional_rift_progress', 0)}%)",
                    )
                except Exception as _exc:
                    sl.warning(
                        "STEP_5",
                        f"[Step 3-Story-Save] 실패 (영향 없음): {_exc}",
                    )

            # -- ARC_STATE_V3: 에피소드 완료 후 arc_state 갱신/저장 (2026-05-02) --
            _arc_v3_enabled = os.environ.get("ARC_STATE_V3_ENABLED", "false").lower() == "true"
            if _arc_v3_enabled and ctx.get("_arc_state") is not None:
                try:
                    from engine.arc.arc_state_engine import save_arc_state as _arc_save
                    from engine.arc.arc_state_engine import (
                        snapshot_to_daily_analysis as _arc_snap,
                    )
                    from engine.arc.arc_state_engine import (
                        update_after_episode as _arc_update,
                    )

                    _outcome_v3 = (ctx.get("battle_result") or {}).get("outcome", "DRAW")
                    _ep_type_v3 = ctx.get("episode_type_v3") or ctx.get(
                        "scenario_type", "ONE_VS_ONE"
                    )
                    _snap_row = ctx.get("_snapshot_row") or {}
                    _new_villain = ctx.get("_new_villain_id")
                    _open_hook_v3 = (script_dict or {}).get("next_hook")

                    _updated_arc = _arc_update(
                        state=ctx["_arc_state"],
                        outcome=_outcome_v3,
                        episode_type=_ep_type_v3,
                        snapshot=_snap_row,
                        new_villain=_new_villain,
                        open_hook=_open_hook_v3,
                    )
                    _arc_save(_updated_arc)
                    _arc_snap(
                        episode_date=episode_date,
                        state=_updated_arc,
                        episode_type_v3=_ep_type_v3,
                    )
                    sl.info(
                        "STEP_5",
                        f"[ARC_V3] arc_state 갱신 완료 "
                        f"(arc_day={_updated_arc['arc_day']} "
                        f"tension={_updated_arc['arc_tension']} "
                        f"sig={_updated_arc['villain_signature']})",
                    )
                except Exception as _arc_exc:
                    sl.warning(
                        "STEP_5",
                        f"[ARC_V3] arc_state 갱신 실패 (영향 없음): {_arc_exc}",
                    )

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
