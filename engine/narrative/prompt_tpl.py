"""
engine/narrative/prompt_tpl.py
Claude 사용자 프롬프트 Jinja2 렌더링.
프롬프트 원본은 Public repo에 노출되지 않도록
Notion에 저장하고 런타임에 로드한다.

v2.0 변경사항 (2026-04-18):
- render_user_prompt(): scenario_type, ending_tone, heroes 파라미터 추가 (기본값 포함).
- template.render()에 3개 변수 주입 → Notion 템플릿의 {{ scenario_type }} 등 치환 가능.
- 후방 호환: 기본값으로 기존 ONE_VS_ONE 동작 유지.

v2.1 변경사항 (2026-04-22 — Step 3-Story 보정):
- render_user_prompt(): guest_character_prompt 파라미터 추가 (기본값 "").
- template.render()에 guest_character_prompt 변수 주입 → Notion 템플릿의
  {% if guest_character_prompt %}{{ guest_character_prompt }}{% endif %} 블록에서 치환.
- 후방 호환: 기본값 ""으로 기존 동작 그대로 유지 (블록 자체가 스킵됨).
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import DictLoader, Environment, select_autoescape

_CANON_PATH = Path("config/characters.yaml")


def _load_canon() -> dict:
    """Load canon from Notion first, fallback to local YAML for tests/dev."""
    try:
        from engine.common.notion_loader import load_characters_canon

        return load_characters_canon()
    except Exception:
        import yaml

        if not _CANON_PATH.exists():
            return {"heroes": {}, "villains": {}}
        return yaml.safe_load(_CANON_PATH.read_text(encoding="utf-8")) or {
            "heroes": {}, "villains": {}
        }


def _canon_prompt_for(canon: dict, char_id: str) -> dict:
    """Return character canon prompt card from nested or top-level canon config."""
    heroes = canon.get("heroes", {}) or {}
    villains = canon.get("villains", {}) or {}
    entry = heroes.get(char_id) or villains.get(char_id) or {}
    top_level = (canon.get("canon_prompts", {}) or {}).get(char_id, {})
    card = dict(top_level)
    card.update(entry.get("canon_prompt") or {})
    if not card:
        return {}
    return card


def build_active_character_cards(
    *,
    canon: dict,
    hero_ids: list[str],
    villain_id: str | None = None,
    villain_ids: list[str] | None = None,
    neutral_guest_ids: list[str] | None = None,
) -> list[dict]:
    """Build compact narrative/visual canon cards for active characters."""
    cards: list[dict] = []
    heroes = canon.get("heroes", {}) or {}
    villains = canon.get("villains", {}) or {}
    neutral_guest_ids = neutral_guest_ids or []
    ordered_ids = [*hero_ids]
    if villain_ids is not None:
        ordered_ids.extend(villain_ids)
    elif villain_id:
        ordered_ids.append(villain_id)
    ordered_ids.extend(neutral_guest_ids)

    seen: set[str] = set()
    for char_id in ordered_ids:
        if not char_id or char_id in seen:
            continue
        seen.add(char_id)
        entry = heroes.get(char_id) or villains.get(char_id) or {}
        canon_prompt = _canon_prompt_for(canon, char_id)
        if not canon_prompt:
            continue
        cards.append({
            "char_id": char_id,
            "name_ko": entry.get("name_ko", canon_prompt.get("name_ko", char_id)),
            "name_en": entry.get("name_en", canon_prompt.get("name_en", char_id)),
            "narrative_identity": canon_prompt.get("narrative_identity", ""),
            "entrance_cue": canon_prompt.get("entrance_cue", []),
            "voice": canon_prompt.get("voice", {}),
            "market_metaphor": canon_prompt.get("market_metaphor", []),
            "signature_action": canon_prompt.get("signature_action", []),
            "forbidden": canon_prompt.get("forbidden", []),
            "panel_rules": canon_prompt.get("panel_rules", {}),
        })
    return cards


def _append_character_cards_fallback(rendered: str, cards: list[dict] | None) -> str:
    """Append character canon cards if runtime template has not been updated."""
    if not cards or "Active Character Canon Cards" in rendered:
        return rendered
    lines = ["", "## Active Character Canon Cards (Pilot — CANON PROMPT LOCK)"]
    for card in cards:
        voice = card.get("voice") or {}
        lines.append(f"### {card.get('char_id')} — {card.get('name_ko') or card.get('name_en')}")
        if card.get("narrative_identity"):
            lines.append(f"- narrative_identity: {card['narrative_identity']}")
        if voice:
            tone = voice.get("tone", "") if isinstance(voice, dict) else str(voice)
            catchphrases = voice.get("catchphrases", []) if isinstance(voice, dict) else []
            lines.append(f"- voice_tone: {tone}")
            if catchphrases:
                lines.append(f"- catchphrases: {'; '.join(catchphrases)}")
        for key in ("entrance_cue", "market_metaphor", "signature_action", "forbidden"):
            vals = card.get(key) or []
            if vals:
                lines.append(f"- {key}: {'; '.join(vals)}")
        panel_rules = card.get("panel_rules") or {}
        if panel_rules:
            lines.append("- panel_rules: " + "; ".join(f"{k}={v}" for k, v in panel_rules.items()))
    return rendered + "\n" + "\n".join(lines)


def _make_jinja_env_from_string(template_str: str) -> Environment:
    env = Environment(
        loader=DictLoader({"narrative_user.j2": template_str}),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"] = lambda val, indent=None: json.dumps(
        val, ensure_ascii=False, indent=indent
    )
    return env


def _append_narrative_context_fallback(rendered: str, context_pack: dict | None) -> str:
    """Append pilot context if a runtime Notion template has not been updated yet."""
    if not context_pack or "Narrative Context Pack" in rendered:
        return rendered

    lines = [
        "",
        "## Narrative Context Pack (Pilot — DATA/STORY GROUNDING)",
        f"- market_cause: {context_pack.get('market_cause', '')}",
        f"- battle_outcome: {context_pack.get('battle_outcome', '')}",
    ]
    top_evidence = context_pack.get("top_evidence") or []
    if top_evidence:
        lines.append("### Evidence Cards (use only these facts; do not invent data)")
        for ev in top_evidence:
            value = ev.get("value") or ev.get("headline_summary") or ""
            lines.append(
                f"- {ev.get('id', '')} | {ev.get('kind', '')} | {value} | "
                f"story_role={ev.get('story_role', '')}"
            )
    previous_episode = context_pack.get("previous_episode") or {}
    if previous_episode:
        lines.append("### Previous Episode Continuity")
        lines.append(f"- source_episode_id: {previous_episode.get('source_episode_id', '')}")
        lines.append(f"- title: {previous_episode.get('title', '')}")
        lines.append(f"- previous_final_panel: {previous_episode.get('final_panel_summary', '')}")
        lines.append(f"- previous_next_hook: {previous_episode.get('next_hook', '')}")
        unresolved = previous_episode.get("unresolved_threads") or []
        if unresolved:
            lines.append("- unresolved_threads: " + "; ".join(str(item) for item in unresolved))
        lines.append(f"- must_continue_from: {previous_episode.get('must_continue_from', '')}")
    directives = context_pack.get("continuity_directives") or []
    if directives:
        lines.append("### Continuity Directives")
        lines.extend(f"- {directive}" for directive in directives)
    foreshadow = context_pack.get("foreshadow") or []
    if foreshadow:
        lines.append("### Next Event Cards")
        lines.extend(f"- {hook}" for hook in foreshadow)
    scene_symbols = context_pack.get("scene_symbols") or []
    if scene_symbols:
        lines.append("### Scene Symbol Candidates")
        lines.extend(f"- {symbol}" for symbol in scene_symbols)
    prohibited_claims = context_pack.get("prohibited_claims") or []
    if prohibited_claims:
        lines.append("### Factuality Guardrails")
        lines.extend(f"- {claim}" for claim in prohibited_claims)
    return rendered + "\n" + "\n".join(lines)


def _append_story_beat_plan_fallback(rendered: str, story_beat_plan: dict | None) -> str:
    """Append pilot beat plan if a runtime Notion template has not been updated yet."""
    if not story_beat_plan or "Story Beat Plan" in rendered:
        return rendered

    lines = [
        "",
        "## Story Beat Plan (Pilot — follow this 8-panel contract)",
        f"- episode_thesis: {story_beat_plan.get('episode_thesis', '')}",
        f"- market_cause_summary: {story_beat_plan.get('market_cause_summary', '')}",
        f"- villain_motivation: {story_beat_plan.get('villain_motivation', '')}",
        f"- hero_inner_conflict: {story_beat_plan.get('hero_inner_conflict', '')}",
        f"- next_hook_seed: {story_beat_plan.get('next_hook_seed', '')}",
    ]
    for beat in story_beat_plan.get("panel_beats") or []:
        evidence = ", ".join(beat.get("market_evidence_ids") or [])
        characters = ", ".join(beat.get("required_character") or [])
        continuity = beat.get("continuity_payoff") or ""
        continuity_suffix = f"; continuity={continuity}" if continuity else ""
        lines.append(
            f"P{beat.get('panel_idx')} {beat.get('dramatic_function')} — "
            f"evidence={evidence}; characters={characters}; "
            f"visual={beat.get('visual_symbol', '')}; intent={beat.get('dialogue_intent', '')}"
            f"{continuity_suffix}"
        )
    return rendered + "\n" + "\n".join(lines)


def _append_always_on_grounding_guardrails(rendered: str) -> str:
    """Append factuality guardrails that must survive disabled pilot context.

    The Narrative Context Pack has richer evidence cards, but the production
    workflow can run with NARRATIVE_CONTEXT_ENABLED=false.  In that mode Claude
    still receives market deltas and may choose the Algorithm Reaper motif; make
    sure it does not turn that motif into unsupported real-market claims.
    """
    marker = "Always-on Market Grounding Guardrails"
    if marker in rendered:
        return rendered
    lines = [
        "",
        f"## {marker}",
        "- market_ref must cite only supplied delta numbers or supplied evidence cards.",
        "- Do not claim algo-trading volume, abnormal trading spikes, algo cascade "
        "detection, cascade collapse, or circuit-driven order flow unless supplied "
        "evidence explicitly states it.",
        "- Algorithm Reaper may appear as a fictional character/metaphor, but not as "
        "a real market-data source or measured trading-volume fact.",
    ]
    return rendered + "\n" + "\n".join(lines)


def render_user_prompt(
    date: str,
    episode_id: str,
    event_type: str,
    delta: dict,
    battle_result: dict,
    hero_id: str,
    villain_id: str,
    arc_context: dict,
    # ── v2.0 신규 파라미터 (기본값으로 하위 호환 보장) ────────────────────────
    scenario_type: str = "ONE_VS_ONE",
    ending_tone: str = "TENSE",
    heroes: list[str] | None = None,
    # ── Step 3-Story 신규 파라미터 (2026-04-22 보정) ──────────────────────────
    guest_character_prompt: str = "",
    # ── Phase 2.3 신규 파라미터 (G02 BS_PR_RULES) ─────────────────────────────
    narrative_depth_enabled: bool = False,
    pair_tension_enabled: bool = False,
    triggered_pair: str | None = None,
    hero_belief: dict | None = None,
    villain_belief: dict | None = None,
    # ── Narrative enrichment pilot (2026-06-01) ───────────────────────────────
    narrative_context_pack: dict | None = None,
    story_beat_plan: dict | None = None,
    active_character_cards: list[dict] | None = None,
    villain_ids: list[str] | None = None,
) -> str:
    """
    Notion에서 로드한 narrative_user 템플릿 렌더링.

    Args:
        date:          에피소드 날짜 (YYYY-MM-DD).
        episode_id:    에피소드 ID.
        event_type:    이벤트 타입 (7종).
        delta:         시장 변화 데이터.
        battle_result: 전투 결과 dict.
        hero_id:       주 히어로 ID.
        villain_id:    빌런 ID.
        arc_context:   에피소드 연속성 정보.
        scenario_type: v2.0 — "ONE_VS_ONE" | "NO_BATTLE" | "ALLIANCE" (기본: ONE_VS_ONE).
        ending_tone:   v2.0 — "OPTIMISTIC" | "TENSE" | "OMINOUS" (기본: TENSE).
        heroes:        v2.0 — 히어로 ID 리스트. ALLIANCE=2개, 그 외=1개.
                       None이면 [hero_id] 사용.
        guest_character_prompt: 게스트 캐릭터 프롬프트 블록.
        narrative_depth_enabled: v2.3 — Belief Sheet 블록 출력 여부.
        pair_tension_enabled:    v2.3 — Pair Relationship 블록 출력 여부.
        triggered_pair:          v2.3 — STEP 1.5-B에서 triggered된 페어 ID.
        hero_belief:             v2.3 — 주 히어로 belief 6요소 dict.
        villain_belief:          v2.3 — 빌런 belief 6요소 dict (Oil Shock은 4요소).
        narrative_context_pack:  파일럿 — 시장/뉴스/이벤트 압축 컨텍스트.
        story_beat_plan:         파일럿 — 8컷 서사 설계도.
        active_character_cards:  캐릭터별 카논 프롬프트 카드.
        villain_ids:             다중 빌런 ID 리스트. None이면 villain_id 단일값 사용.

    Returns:
        렌더링된 사용자 프롬프트 문자열.
    """
    from engine.common.notion_loader import load_narrative_user_template

    # heroes 기본값 처리 — None이면 기존 단일 히어로로 fallback
    if heroes is None:
        heroes = [hero_id]

    try:
        template_str = load_narrative_user_template()
    except Exception:
        template_str = Path("config/prompts/narrative_user.j2").read_text(encoding="utf-8")
    canon = _load_canon()
    heroes_canon = canon.get("heroes", {})
    villains = canon.get("villains", {})
    hero_entry = heroes_canon.get(hero_id, {})
    villain_entry = villains.get(villain_id, {})

    # ── Phase 2.3: characters.yaml의 belief 블록 자동 로드 ────────────────────
    # 명시적으로 hero_belief/villain_belief가 전달되지 않으면 canon에서 추출
    if narrative_depth_enabled:
        if hero_belief is None:
            hero_belief = hero_entry.get("belief") or {}
        if villain_belief is None:
            villain_belief = villain_entry.get("belief") or {}

    if active_character_cards is None:
        import os

        if os.environ.get("CHARACTER_CANON_PROMPT_V2_ENABLED", "false").lower() == "true":
            neutral_guest_ids = []
            active_character_cards = build_active_character_cards(
                canon=canon,
                hero_ids=heroes,
                villain_id=villain_id if scenario_type != "NO_BATTLE" else None,
                villain_ids=(villain_ids if scenario_type != "NO_BATTLE" else []),
                neutral_guest_ids=neutral_guest_ids,
            )
        else:
            active_character_cards = []

    env = _make_jinja_env_from_string(template_str)
    template = env.get_template("narrative_user.j2")

    rendered = template.render(
        date=date,
        episode_id=episode_id,
        event_type=event_type,
        delta=delta,
        battle_result=battle_result,
        hero_id=hero_id,
        hero_name=hero_entry.get("name_ko", hero_id),
        villain_id=villain_id,
        villain_ids=villain_ids or ([villain_id] if scenario_type != "NO_BATTLE" else []),
        villain_name=villain_entry.get("name_ko", villain_id),
        arc_context=arc_context,
        heroes=heroes_canon,
        villains=villains,
        scenario_type=scenario_type,
        ending_tone=ending_tone,
        hero_ids=heroes,
        guest_character_prompt=guest_character_prompt,
        # ── Phase 2.3 신규 변수 ──
        narrative_depth_enabled=narrative_depth_enabled,
        pair_tension_enabled=pair_tension_enabled,
        triggered_pair=triggered_pair,
        hero_belief=hero_belief,
        villain_belief=villain_belief,
        narrative_context_pack=narrative_context_pack or {},
        story_beat_plan=story_beat_plan or {},
        active_character_cards=active_character_cards or [],
    )
    rendered = _append_narrative_context_fallback(rendered, narrative_context_pack)
    rendered = _append_story_beat_plan_fallback(rendered, story_beat_plan)
    rendered = _append_character_cards_fallback(rendered, active_character_cards)
    rendered = _append_always_on_grounding_guardrails(rendered)
    return rendered


def load_system_prompt() -> str:
    """Notion에서 narrative_system_prompt 로드."""
    from engine.common.notion_loader import load_narrative_system

    return load_narrative_system()
