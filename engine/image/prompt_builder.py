"""
engine/image/prompt_builder.py
Gemini 이미지 생성 프롬프트 빌더.

GLOBAL_STYLE_BLOCK, SECURITY_NEGATIVE_BLOCK_V1_1은
Public repo 노출 방지를 위해 Notion에서 런타임 로드.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Fallback 상수 — Notion 로드 실패 시 사용 (최소 보안 수준)
_FALLBACK_STYLE = "Marvel + DC Hybrid Comic Style, ultra detailed, 8k, dark cinematic"
_FALLBACK_NEGATIVE = "No real people, no copyrighted characters, no nudity, comic style only"


def _get_style_block() -> str:
    try:
        from engine.common.notion_loader import load_image_prompt_blocks

        blocks = load_image_prompt_blocks()
        return blocks.get("GLOBAL_STYLE_BLOCK", _FALLBACK_STYLE)
    except Exception as exc:
        logger.warning("[prompt_builder] GLOBAL_STYLE_BLOCK Notion 로드 실패: %s", exc)
        return _FALLBACK_STYLE


def _get_negative_block() -> str:
    try:
        from engine.common.notion_loader import load_image_prompt_blocks

        blocks = load_image_prompt_blocks()
        return blocks.get("SECURITY_NEGATIVE_BLOCK_V1_1", _FALLBACK_NEGATIVE)
    except Exception as exc:
        logger.warning("[prompt_builder] SECURITY_NEGATIVE_BLOCK Notion 로드 실패: %s", exc)
        return _FALLBACK_NEGATIVE


@dataclass
class PanelPrompt:
    panel_idx: int
    char_ids: list[str]
    prompt_text: str
    ref_image_paths: list[Path]


def verify_negative_block_present(prompt_text: str) -> bool:
    """NEGATIVE 블록이 포함되어 있는지 확인."""
    return "NEGATIVE" in prompt_text.upper() or "No real people" in prompt_text


def _get_panel_visual_spec(panel_type: str) -> str:
    """
    패널 타입별 시각적 스펙 블록 생성.
    Notion load_panel_visual_spec()에서 로드, fallback 시 기본값 사용.
    """
    # 패널 타입별 fallback (Notion 로드 실패 시)
    _FALLBACK: dict[str, dict] = {
        "COVER": {
            "composition": "Epic wide shot, both characters visible.",
            "lighting": "Dramatic backlit. Hero: blue rim. Villain: red ambient.",
            "atmosphere": "Cinematic high-stakes confrontation.",
            "camera_rule": "Wide low-angle shot.",
        },
        "TENSION": {
            "composition": "Single character, data screens background.",
            "lighting": "Cool blue monitor glow, deep shadow.",
            "atmosphere": "Analytical tension, quiet calculation.",
            "camera_rule": "Medium shot, slight dutch tilt.",
        },
        "BATTLE": {
            "composition": "Both characters clashing, energy beams colliding center.",
            "lighting": "Explosive clash light. Hero: blue. Villain: red.",
            "atmosphere": "Intense kinetic combat, shockwave debris.",
            "camera_rule": "Low angle dutch tilt, dynamic diagonal.",
        },
        "CLIMAX": {
            "composition": "Decisive peak moment, one character dominant.",
            "lighting": "Blinding white energy burst, maximum contrast.",
            "atmosphere": "Peak dramatic intensity, turning point.",
            "camera_rule": "Extreme low angle, full character visible.",
        },
        "AFTERMATH": {
            "composition": "Single hero, post-battle calm, open skyline.",
            "lighting": "Golden hour warm ambient, smoke dissipating.",
            "atmosphere": "Reflective quiet, dignified resolution.",
            "camera_rule": "Medium wide, eye level, hero facing right.",
        },
        "TEXT_CARD": {
            "composition": "Abstract data visualization, dark background.",
            "lighting": "Neon tech glow, cyan/amber accents.",
            "atmosphere": "Intelligence briefing, clean precision.",
            "camera_rule": "Flat frontal, no characters.",
        },
        "DISCLAIMER": {
            "composition": "Minimal dark background.",
            "lighting": "Soft warm amber center.",
            "atmosphere": "Official, clean, trustworthy.",
            "camera_rule": "Static flat, no characters.",
        },
    }

    try:
        from engine.common.notion_loader import load_panel_visual_spec

        specs = load_panel_visual_spec()
        spec = specs.get(panel_type) or _FALLBACK.get(panel_type, {})
    except Exception as exc:
        logger.warning("[prompt_builder] PANEL_VISUAL_SPEC 로드 실패 (fallback 사용): %s", exc)
        spec = _FALLBACK.get(panel_type, {})

    if not spec:
        return ""

    lines = [
        f"== VISUAL SPEC: {panel_type} ==",
        f"COMPOSITION: {spec.get('composition', '')}",
        f"LIGHTING: {spec.get('lighting', '')}",
        f"ATMOSPHERE: {spec.get('atmosphere', '')}",
        f"CAMERA RULE: {spec.get('camera_rule', '')}",
    ]
    engagement = spec.get("engagement", "")
    if engagement:
        lines.append(f"ENGAGEMENT: {engagement}")
    lines.append("== END VISUAL SPEC ==")
    return "\n".join(lines)


def _build_identity_lock(characters: list[dict], char_design_block: str) -> str:
    """
    Notion 11 Canon Test 검증 패턴 기반 Identity Lock 블록.
    REF 이미지 + 텍스트 양방향으로 캐릭터 일관성 강제.
    """
    if not characters:
        return ""

    lines = [
        "== CHARACTER IDENTITY LOCK ==",
        "REFERENCE IMAGES PROVIDED. Maintain EXACT identity from the reference images.",
        "DO NOT deviate from appearance in ANY panel. Same design ALWAYS.",
        "",
    ]

    # CHAR_DESIGN_SPECS에서 핵심 정보 추출해서 간결하게 재정리
    try:
        from engine.common.notion_loader import load_char_design_blocks

        char_ids = [ch.get("char_id", "") for ch in characters if ch.get("char_id")]
        specs = load_char_design_blocks(char_ids)

        for ch in characters:
            char_id = ch.get("char_id", "")
            role = ch.get("role", "").upper()
            position = ch.get("position", "CENTER")
            facing = "RIGHT" if role == "HERO" else "LEFT"

            spec = specs.get(char_id, {})
            name = spec.get("name", char_id)
            identifier = spec.get("identifier", "")
            color_rule = spec.get("color_rule", "")
            strict = spec.get("strict", "Same design every panel.")

            lines.append(f"CHARACTER {role} — {name}")
            lines.append(f"  Position: {position} side of frame | Facing: {facing}")
            if identifier:
                lines.append(f"  MANDATORY IDENTIFIER: {identifier}")
            if color_rule:
                lines.append(f"  COLOR STRICT: {color_rule}")
            lines.append(f"  CONSISTENCY RULE: {strict}")
            lines.append("")

    except Exception as exc:
        logger.warning("[prompt_builder] Identity Lock 생성 실패 (fallback): %s", exc)
        for ch in characters:
            role = ch.get("role", "").upper()
            position = ch.get("position", "CENTER")
            lines.append(f"CHARACTER {role}: {position} side. Maintain exact reference identity.")
            lines.append("")

    lines.append("== END IDENTITY LOCK ==")
    return "\n".join(lines)


def _get_chart_direction(outcome: str | None) -> str:
    """
    전투 결과(outcome)에 따른 배경 차트 방향 지시.
    EDT CHART DIRECTION RULE 이식 (Content OS 검증).
    """
    if not outcome:
        return ""

    _FALLBACK: dict[str, str] = {
        "HERO_VICTORY": "Background financial charts show GREEN upward lines. Market recovering visual.",
        "HERO_TACTICAL_VICTORY": "Background charts show mixed but trending GREEN. Cautious optimism.",
        "DRAW": "Background charts show NEUTRAL mixed colors. Sideways movement.",
        "VILLAIN_TEMP_VICTORY": "Background charts show RED downward lines. Market pressure visual.",
        "HERO_DEFEAT": "Background charts ALL RED. Steep downward. Emergency warnings. No green anywhere.",
        "SYSTEM_COLLAPSE": "ALL RED ONLY. Catastrophic chart collapse. ERROR screens everywhere. ZERO green allowed.",
    }

    try:
        from engine.common.notion_loader import load_chart_direction_rule

        rules = load_chart_direction_rule()
        direction = rules.get(outcome) or _FALLBACK.get(outcome, "")
    except Exception:
        direction = _FALLBACK.get(outcome, "")

    if not direction:
        return ""
    return f"CHART DIRECTION RULE ({outcome}): {direction}"


def _get_char_designs(char_ids: list[str]) -> str:
    """
    등장 캐릭터 외형 명세 블록 생성.
    Notion load_char_design_blocks()에서 로드, fallback 시 빈 문자열.
    """
    if not char_ids:
        return ""
    try:
        from engine.common.notion_loader import char_design_to_prompt_block, load_char_design_blocks

        specs = load_char_design_blocks(char_ids)
        if not specs:
            return ""
        blocks = []
        for char_id in char_ids:
            if char_id in specs:
                blocks.append(char_design_to_prompt_block(char_id, specs[char_id]))
        return "\n\n".join(blocks)
    except Exception as exc:
        logger.warning("[prompt_builder] CHAR_DESIGN 로드 실패 (무시): %s", exc)
        return ""


def _tone_hint(panel_type: str, key_text: str, narration: str) -> str:
    """
    패널 타입 + 텍스트 내용 → 영문 분위기 힌트 변환.
    Gemini에 한글 내용 노출 없이 장면 톤만 전달.
    """
    tone_map = {
        "COVER": "Epic confrontation, cinematic wide shot, hero vs villain",
        "TENSION": "Rising tension, data analysis, strategic observation",
        "BATTLE": "Intense combat, energy clash, dynamic action",
        "CLIMAX": "Peak moment, decisive strike, maximum intensity",
        "AFTERMATH": "Post-battle calm, reflective mood, quiet observation",
        "TEXT_CARD": "Clean dark background, minimalist, data visualization",
        "DISCLAIMER": "Dark background, official notice, clean typography space",
    }
    base = tone_map.get(panel_type, "Dramatic scene")
    # 한글 감정 키워드 → 영문 변환
    if any(w in key_text for w in ["무승부", "DRAW"]):
        base += ", stalemate energy, balanced forces"
    elif any(w in key_text for w in ["승리", "VICTORY"]):
        base += ", triumphant pose, victory energy"
    elif any(w in key_text for w in ["위험", "DANGER", "위기"]):
        base += ", danger aura, threat energy"
    return base


def build_panel_prompt(
    panel: dict,
    ref_paths: list[Path] | None = None,
    battle_outcome: str | None = None,
) -> str:
    """
    단일 패널 Gemini 프롬프트 생성.

    Args:
        panel: EpisodeScript.panels[i] dict
        ref_paths: 캐릭터 REF 이미지 경로 목록
        battle_outcome: 전투 결과 (HERO_VICTORY / DRAW / SYSTEM_COLLAPSE 등)
                        CHART DIRECTION RULE 적용에 사용.

    Returns:
        완성된 프롬프트 문자열.
    """
    style_block = _get_style_block()
    negative_block = _get_negative_block()

    panel_type = panel.get("panel_type", "BATTLE")
    setting = panel.get("setting", "Financial district")
    action = panel.get("action", "")
    key_text = panel.get("key_text", "")
    narration = panel.get("narration", "")
    market_ref = panel.get("market_ref", "")
    camera = panel.get("camera", "MEDIUM")

    # 캐릭터 정보
    characters = panel.get("characters", [])
    char_desc_lines: list[str] = []
    for ch in characters:
        role = ch.get("role", "")
        char_id = ch.get("char_id", "")
        position = ch.get("position", "CENTER")
        char_desc_lines.append(f"{role.upper()} ({char_id}): position={position}")

    char_desc = "\n".join(char_desc_lines) if char_desc_lines else "No characters"

    # 장면 톤 힌트 (한글 내용 대신 분위기만 전달)
    tone_hint = _tone_hint(panel_type, key_text, narration)

    # 패널 타입별 시각적 스펙 (조명/구도/분위기) — Notion에서 로드
    visual_spec_block = _get_panel_visual_spec(panel_type)

    # 캐릭터별 외형 고정 명세 블록 (Notion에서 로드)
    char_ids = [ch.get("char_id", "") for ch in characters if ch.get("char_id")]
    char_design_block = _get_char_designs(char_ids)

    # Identity Lock 블록 (Notion 11 Canon Test 검증 패턴)
    identity_lock_block = _build_identity_lock(characters, char_design_block)

    lines = [
        # ── 최우선 규칙: 텍스트 절대 금지 ──────────────────────────────
        "CRITICAL RULE: PURE VISUAL SCENE ONLY.",
        "ABSOLUTELY NO TEXT, LETTERS, KOREAN, JAPANESE, CHINESE, LATIN, NUMBERS, SPEECH BUBBLES, CAPTION BOXES, or any TYPOGRAPHY in the image.",
        "Market data HUD displays on screens are permitted only as blurred background elements, NOT readable text.",
        "",
        "== STYLE LOCK ==",
        style_block,
        "== END STYLE LOCK ==",
        "",
        f"PANEL TYPE: {panel_type}",
        f"CAMERA: {camera}",
        f"SETTING: {setting}",
        f"ACTION: {action}",
        f"SCENE TONE: {tone_hint}",
        "",
    ]

    # 패널 타입별 시각적 스펙 주입 (조명/구도/분위기/engagement)
    if visual_spec_block:
        lines += [visual_spec_block, ""]

    # CHART DIRECTION RULE — outcome 기반 배경 차트 색상 (BATTLE/CLIMAX에만 의미 있음)
    chart_dir = _get_chart_direction(battle_outcome or panel.get("battle_outcome"))
    if chart_dir and panel_type in ("BATTLE", "CLIMAX", "AFTERMATH"):
        lines += [chart_dir, ""]

    # Identity Lock (캐릭터 있는 패널만)
    if identity_lock_block:
        lines += [identity_lock_block, ""]

    # 캐릭터 위치 + 외형 명세
    if characters:
        lines += [
            "CHARACTERS (position only):",
            char_desc,
            "",
        ]
        if char_design_block:
            lines += [
                "== CHARACTER DESIGN SPECS — STRICT, DO NOT DEVIATE ==",
                char_design_block,
                "== END CHARACTER DESIGN SPECS ==",
                "CRITICAL: ALL characters MUST match EXACTLY as described above in EVERY panel.",
                "No design variations allowed between panels. Same costume, same weapon, same identifier.",
                "",
            ]

    lines += [
        f"MARKET_CONTEXT (visual mood only, no text): {market_ref or 'general market'}",
        "",
        negative_block,
    ]

    if ref_paths:
        lines.append(f"\nREF IMAGES: {len(ref_paths)} character reference(s) provided.")

    return "\n".join(lines)


def build_for_episode(episode_script: dict) -> list[PanelPrompt]:
    """
    에피소드 전체 패널 프롬프트 생성.

    Args:
        episode_script: EpisodeScript JSON dict

    Returns:
        PanelPrompt 리스트 (panels 순서 동일).
    """
    from engine.common.exceptions import CanonLockViolation
    from engine.image.ref_loader import get_refs_for_panel

    panels = episode_script.get("panels", [])
    panel_prompts: list[PanelPrompt] = []

    for panel in panels:
        idx = panel.get("idx", 0)
        char_ids = [ch.get("char_id", "") for ch in panel.get("characters", [])]

        # REF 이미지 로드 — char_ids 리스트 전체를 한 번에 전달
        ref_paths: list[Path] = []
        try:
            valid_char_ids = [c for c in char_ids if c]
            if valid_char_ids:
                ref_paths = get_refs_for_panel(valid_char_ids)
        except CanonLockViolation as exc:
            logger.error("[prompt_builder] Canon Lock 위반: %s", exc)
            raise

        prompt_text = build_panel_prompt(panel, ref_paths)
        panel_prompts.append(
            PanelPrompt(
                panel_idx=idx,
                char_ids=char_ids,
                prompt_text=prompt_text,
                ref_image_paths=ref_paths,
            )
        )

    logger.info("[prompt_builder] %d개 패널 프롬프트 생성 완료", len(panel_prompts))
    return panel_prompts
