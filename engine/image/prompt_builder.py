"""
engine/image/prompt_builder.py
Gemini 이미지 생성 프롬프트 빌더.

GLOBAL_STYLE_BLOCK, SECURITY_NEGATIVE_BLOCK_V1_1은
Public repo 노출 방지를 위해 Notion에서 런타임 로드.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Fallback 상수 — Notion 로드 실패 시 사용 (최소 보안 수준)
_FALLBACK_STYLE = "Korean manhwa-influenced superhero comic, bold ink lines, dark cinematic"
_FALLBACK_NEGATIVE = "No real people, no copyrighted characters, no nudity, comic style only"


def _get_style_block() -> str:
    try:
        from engine.common.notion_loader import load_image_prompt_blocks

        blocks = load_image_prompt_blocks()
        style = blocks.get("GLOBAL_STYLE_BLOCK", _FALLBACK_STYLE)
    except Exception as exc:
        logger.warning("[prompt_builder] GLOBAL_STYLE_BLOCK Notion 로드 실패: %s", exc)
        style = _FALLBACK_STYLE
    # The runtime page still forbids flat cel shading, contradicting the checked-in
    # shading=cel canon. Keep staging rules but remove that legacy negative line.
    style = re.sub(r"(?im)^.*no flat cel[- ]shading.*$", "", style)
    # Keep visual technique while removing the legacy publisher/artist identity
    # request that contradicts the same runtime page's original-character rule.
    style = style.replace(
        "DC Comics graphic novel style — Frank Miller / Jim Lee quality.",
        "Original financial superhero graphic novel illustration; bold precise ink and cinematic staging.",
    )
    style = re.sub(
        r"(?s)== PROPORTION MANDATE ==.*?== END PROPORTION MANDATE ==",
        "== PROPORTION MANDATE ==\n"
        "For humanoid characters only: tall lean proportions, elongated torso and long limbs.\n"
        "For non-human characters: preserve the exact REF anatomy; never add human limbs, faces or eyes.\n"
        "Armour follows the reference-defined silhouette.\n== END PROPORTION MANDATE ==",
        style,
    )
    return (style + "\nCANON RENDERING LOCK: 2D cinematic comic illustration, bold precise ink "
            "lines, cel-shaded shadows and high-contrast neon accents on a dark background. "
            "No photorealism, 3D rendering, plastic toy shading or sculpted render surfaces.")


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
        "Use each character's provided reference image and approved visual contract, including guests.",
        "Copy character identity only. Never copy reference backgrounds, corner symbols or watermarks.",
        "DO NOT deviate from appearance in ANY panel. Same design ALWAYS.",
        "",
    ]

    from engine.character.guest_visuals import guest_visual_spec
    from engine.common.notion_loader import load_char_design_blocks
    from engine.image.ref_loader import GUEST_CHARACTER_IDS

    # A runtime lookup failure must never remove a guest's local identity lock.
    canon_ids = [ch.get("char_id") for ch in characters
                 if ch.get("char_id") and ch["char_id"] not in GUEST_CHARACTER_IDS]
    try:
        specs = load_char_design_blocks(canon_ids) if canon_ids else {}
    except Exception as exc:
        logger.warning("[prompt_builder] Canon identity lookup unavailable: %s", exc)
        specs = {}

    for ch in characters:
        char_id = ch.get("char_id", "")
        role = ch.get("role", "").upper()
        position = ch.get("position", "CENTER")
        facing = "RIGHT" if role == "HERO" else "LEFT"
        # Validate outside the runtime fallback: a missing guest contract is fatal.
        spec = guest_visual_spec(char_id) if char_id in GUEST_CHARACTER_IDS else specs.get(char_id, {})
        lines.append(f"CHARACTER {role} — {char_id}: {spec.get('name', char_id)}")
        lines.append(f"  Position: {position} side of frame | Facing: {facing}")
        for key, label in (("body", "FIXED BODY AND FACE"),
                           ("costume", "FIXED COSTUME"),
                           ("weapon", "FIXED WEAPON"),
                           ("identifier", "MANDATORY IDENTIFIER"),
                           ("color_rule", "COLOR STRICT")):
            if spec.get(key):
                lines.append(f"  {label}: {spec[key]}")
        lines.append(f"  CONSISTENCY RULE: {spec.get('strict', 'Maintain exact reference identity.')}")
        lines.append("  Preserve identity across all panels. Only pose, camera and lighting may change.")
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
        "SYSTEM_COLLAPSE": "ALL RED ONLY. Catastrophic chart collapse. Abstract warning lights. ZERO green allowed.",
    }

    # Chart instructions are deterministic: runtime prose can request numbers or
    # labelled ERROR displays that contradict the no-typography contract.
    direction = _FALLBACK.get(outcome, "")
    if not direction:
        return ""
    return f"CHART DIRECTION RULE ({outcome}): {direction} Abstract unlabelled lines only."


def _get_local_canon_designs(char_ids: list[str]) -> str:
    """Fallback visual canon cards from config/characters.yaml canon_prompts."""
    if not char_ids:
        return ""
    try:
        import yaml

        canon_path = Path("config/characters.yaml")
        if not canon_path.exists():
            return ""
        canon = yaml.safe_load(canon_path.read_text(encoding="utf-8")) or {}
        prompts = canon.get("canon_prompts", {}) or {}
        heroes = canon.get("heroes", {}) or {}
        villains = canon.get("villains", {}) or {}
        blocks: list[str] = []
        for char_id in char_ids:
            card = prompts.get(char_id) or {}
            if not card:
                continue
            entry = heroes.get(char_id) or villains.get(char_id) or {}
            name = entry.get("name_en") or entry.get("name_ko") or char_id
            blocks.append(f"== LOCAL CANON DESIGN: {name} ==")
            if card.get("narrative_identity"):
                blocks.append(f"Identity: {card['narrative_identity']}")
            for key, label in (
                ("entrance_cue", "Entrance Cue"),
                ("market_metaphor", "Market Metaphor"),
                ("signature_action", "Signature Action"),
                ("forbidden", "Forbidden Visuals — HARD ERRORS"),
            ):
                vals = card.get(key) or []
                if vals:
                    blocks.append(f"{label}: {'; '.join(vals)}")
            panel_rules = card.get("panel_rules") or {}
            if panel_rules:
                blocks.append("Panel Rules: " + "; ".join(f"{k}={v}" for k, v in panel_rules.items()))
            blocks.append(f"== END LOCAL CANON DESIGN: {name} ==")
        return "\n".join(blocks)
    except Exception as exc:
        logger.warning("[prompt_builder] local canon design 로드 실패 (무시): %s", exc)
        return ""


def _get_char_designs(char_ids: list[str]) -> str:
    """
    등장 캐릭터 외형 명세 블록 생성.
    Notion load_char_design_blocks()에서 로드, fallback 시 빈 문자열.
    """
    if not char_ids:
        return ""
    from engine.common.exceptions import PipelineAborted
    from engine.image.ref_loader import GUEST_CHARACTER_IDS

    try:
        from engine.common.notion_loader import char_design_to_prompt_block, load_char_design_blocks
        specs = load_char_design_blocks(char_ids)
    except Exception as exc:
        logger.warning("[prompt_builder] CHAR_DESIGN unavailable: %s", exc)
        specs = {}
    blocks = []
    for char_id in char_ids:
        if char_id in GUEST_CHARACTER_IDS:
            from engine.character.guest_visuals import guest_visual_block

            blocks.append(guest_visual_block([char_id]))
            continue
        spec = specs.get(char_id)
        if spec:
            block = char_design_to_prompt_block(char_id, spec)
        else:
            block = _get_local_canon_designs([char_id])
        if not block:
            raise PipelineAborted("prompt", f"Missing character design: {char_id}")
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


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
    performance_spec: object | None = None,
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
    from engine.common.exceptions import PipelineAborted

    style_block = _get_style_block()
    negative_block = _get_negative_block()

    panel_type = panel.get("panel_type", "BATTLE")
    outcome = battle_outcome or panel.get("battle_outcome")
    no_battle = panel.get("scenario_type") == "NO_BATTLE" or outcome == "NO_BATTLE"
    background_only = panel_type in {"TEXT_CARD", "DISCLAIMER"}
    setting = panel.get("setting", "Financial district")
    action = panel.get("action", "")
    if panel_type == "TEXT_CARD":
        action = ("Abstract neutral light shapes on a dark background. No chart, arrows, "
                  "tickers, numbers, labels, readable text or implied market direction. "
                  "Market facts are added by the compositor, not drawn into this image.")
    key_text = panel.get("key_text", "")
    narration = panel.get("narration", "")
    market_ref = panel.get("market_ref", "")
    camera = panel.get("camera", "MEDIUM")

    # 캐릭터 정보
    characters = panel.get("characters", [])
    if background_only and characters:
        raise PipelineAborted("prompt", f"{panel_type} cannot contain characters")
    ids = [ch.get("char_id", "") for ch in characters]
    if any(not char_id for char_id in ids) or len(ids) != len(set(ids)):
        raise PipelineAborted("prompt", "Invalid or duplicate character cast")
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
    if background_only:
        tone_hint = "Clean abstract background without characters or typography"
        visual_spec_block = "COMPOSITION: Abstract environment only; no characters, silhouettes, bodies, weapons or faces."
    elif no_battle and panel.get("_action_mode") == "TACTICAL_ACTION":
        tone_hint = "Urgent non-combat tactical action; visible state change"
        visual_spec_block = ("COMPOSITION: Show the declared tracking, evasion, rescue or barrier "
                             "operation using only approved characters. No attacks or combat verdict.")
    elif no_battle:
        tone_hint = "Strategic observation, quiet non-combat scene"
        visual_spec_block = "COMPOSITION: Non-combat strategic observation. No attacks or forced confrontation."
    elif outcome == "DRAW" and panel_type in {"COVER", "BATTLE", "CLIMAX", "AFTERMATH"}:
        tone_hint = "Unresolved stalemate, balanced forces"
        visual_spec_block = "COMPOSITION: Both opposing forces remain at equal scale. Balanced stalemate; neither side dominant, defeated or retreating."
    else:
        # Runtime compositions can assume a single character for multi-cast panels.
        visual_spec_block = "\n".join(
            (f"COMPOSITION: Exactly the approved cast ({len(ids)} characters); staging follows the declared action."
             if line.startswith("COMPOSITION:") else line)
            for line in visual_spec_block.splitlines()
        )

    # 캐릭터별 외형 고정 명세 블록 (Notion에서 로드)
    char_ids = [ch.get("char_id", "") for ch in characters if ch.get("char_id")]
    char_design_block = _get_char_designs(char_ids)

    # Identity Lock 블록 (Notion 11 Canon Test 검증 패턴)
    identity_lock_block = _build_identity_lock(characters, char_design_block)

    lines = [
        # ── 최우선 규칙: 텍스트 절대 금지 ──────────────────────────────
        "CRITICAL RULE: PURE VISUAL SCENE ONLY.",
        "CONTEXT: Original fictional financial-fantasy characters; all human characters are adults. "
        "Depict non-graphic symbolic market forces, with no injury to people. "
        "Preserve the approved reference identities and canon props.",
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
        "",
        "== DYNAMIC ACTION (MUST BE DEPICTED) ==",
        f"{action}",
        "REQUIREMENT: Render this exact action as the visual focal point.",
        ("No characters, limbs, faces or character poses. Depict only the requested abstract environment."
         if background_only or not characters else
         "Depict intent and motion appropriate to each reference-defined species. Never invent limbs, faces, eyes or human anatomy."),
        "The character reference (REF) images define appearance ONLY (costume, face, weapon design), NOT pose or stance.",
        "== END DYNAMIC ACTION ==",
        "",
        f"SCENE TONE: {tone_hint}",
        "",
    ]

    if performance_spec is not None:
        spec = (
            performance_spec.model_dump()
            if hasattr(performance_spec, "model_dump")
            else dict(performance_spec)
        )
        mechanics = spec.get("body_mechanics") or {}
        staging = spec.get("staging") or {}
        required = spec.get("required_character_ids") or []
        if len(required) != len(set(required)) or set(required) != set(ids):
            raise PipelineAborted("prompt", "Performance cast differs from panel cast")
        if background_only and (spec.get("subject_id") or spec.get("target_id")):
            raise PipelineAborted("prompt", "Character performance on background-only panel")
        for key in ("subject_id", "target_id"):
            if spec.get(key) and spec[key] not in required:
                raise PipelineAborted("prompt", f"Performance {key} outside required cast")
        lines += [
            "== PERFORMANCE CONTRACT — HARD REQUIREMENT ==",
            f"REQUIRED CHARACTER COUNT: exactly {len(required)} required character(s): {', '.join(required)}",
            f"SUBJECT: {spec.get('subject_id') or 'none'}",
            f"ACTION PHASE: {spec.get('action_phase', 'NONE')}",
            f"ACTION: {spec.get('action_verb', '')}",
            f"INTENT: {spec.get('intent', '')}",
            f"TARGET: {spec.get('target_id') or 'none'}",
            f"VISIBLE CONTACT: {spec.get('contact_point') or 'none required'}",
            f"FOCAL POINT: {staging.get('focal_point', '')}",
            "Performance applies only to existing cast; empty cast requires no body or pose.",
            "Never omit a required character or duplicate a character.",
            "== END PERFORMANCE CONTRACT ==",
            "",
            "== BODY MECHANICS ==",
            "SPECIES PRECEDENCE: Character canon and REF anatomy override generic human body mechanics. For formless or armoured non-human beings, use only canon-defined body structures.",
            f"LEAD: {mechanics.get('lead_limb') or 'not applicable'}",
            f"BASE: {mechanics.get('support_limb') or 'stable and anatomically plausible'}",
            f"WEIGHT: {mechanics.get('weight_direction') or 'balanced for the action'}",
            f"TORSO: {mechanics.get('torso') or 'anatomically plausible'}",
            f"GAZE: {mechanics.get('gaze', '')}",
            f"EXPRESSION: {mechanics.get('expression', '')}",
            f"SECONDARY MOTION: {mechanics.get('secondary_motion') or 'none required'}",
            "== END BODY MECHANICS ==",
            "",
        ]

    if not characters and performance_spec is not None:
        mechanics_start = lines.index("== BODY MECHANICS ==")
        mechanics_end = lines.index("== END BODY MECHANICS ==", mechanics_start)
        del lines[mechanics_start:mechanics_end + 1]

    # 패널 타입별 시각적 스펙 주입 (조명/구도/분위기/engagement)
    if visual_spec_block:
        lines += [visual_spec_block, ""]

    # CHART DIRECTION RULE — outcome 기반 배경 차트 색상 (BATTLE/CLIMAX에만 의미 있음)
    chart_dir = _get_chart_direction(outcome)
    if chart_dir and panel_type in ("BATTLE", "CLIMAX", "AFTERMATH"):
        lines += [chart_dir, ""]

    # Identity Lock (캐릭터 있는 패널만)
    if identity_lock_block:
        lines += [identity_lock_block, ""]

    # 캐릭터 위치 + 외형 명세
    if characters:
        lines += [
            "CHARACTERS (position only — pose follows DYNAMIC ACTION above):",
            char_desc,
            "",
        ]
        if char_design_block:
            lines += [
                "== CHARACTER DESIGN SPECS — APPEARANCE ONLY (NOT pose) ==",
                char_design_block,
                "== END CHARACTER DESIGN SPECS ==",
                "CRITICAL SCOPE: These specs lock APPEARANCE (costume, face features, weapon design, color palette, identifying marks) across all panels.",
                "Same costume, same weapon, same identifier — but pose, stance, and action MUST follow the DYNAMIC ACTION block above.",
                "Do NOT inherit standing/neutral poses from REF images — those are appearance references only.",
                "",
            ]

    lines += [
        f"MARKET_CONTEXT (visual mood only, no text): {market_ref or 'general market'}",
        "",
        negative_block,
        "FINAL PRIORITY: No readable typography or numbers; any runtime request for chart labels, positive numbers or ERROR text is replaced by abstract unlabelled geometry.",
        f"CAST PRIORITY: Render exactly {len(ids)} approved character(s); never omit, duplicate, add or replace a cast member. Generic composition counts never override this cast.",
        "CANON PRIORITY: Exact reference species, fixed anatomy, handedness and required facing direction override generic human anatomy, role-based facing, facial-expression and limb instructions. No unregistered characters.",
    ]

    if ref_paths:
        lines.append(f"\nREF IMAGES: {len(ref_paths)} character reference(s) provided.")

    return "\n".join(lines)


def build_for_episode(
    episode_script: dict,
    performance_specs: list[object] | None = None,
    battle_outcome: str | None = None,
) -> list[PanelPrompt]:
    """
    에피소드 전체 패널 프롬프트 생성.

    Args:
        episode_script: EpisodeScript JSON dict

    Returns:
        PanelPrompt 리스트 (panels 순서 동일).
    """
    from engine.common.exceptions import CanonLockViolation, PipelineAborted
    from engine.image.ref_loader import get_refs_for_panel

    panels = episode_script.get("panels", [])
    panel_prompts: list[PanelPrompt] = []

    specs_by_idx = {
        int(getattr(spec, "panel_idx", 0) or (spec.get("panel_idx", 0) if isinstance(spec, dict) else 0)): spec
        for spec in (performance_specs or [])
    }

    if performance_specs:
        panel_indices = [panel.get("idx", 0) for panel in panels]
        if (len(specs_by_idx) != len(performance_specs)
                or len(panel_indices) != len(set(panel_indices))
                or set(specs_by_idx) != set(panel_indices)):
            raise PipelineAborted("prompt", "Incomplete or duplicate performance panel contracts")

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

        expected_refs = [c for c in char_ids if c]
        if len(ref_paths) != len(expected_refs) or any(not path.is_file() for path in ref_paths):
            raise PipelineAborted("prompt", f"Incomplete character references for panel {idx}")
        effective_panel = dict(panel)
        decision = episode_script.get("_episode_decision") or {}
        if decision and panel.get("scenario_type") not in {None, decision["scenario_type"]}:
            raise PipelineAborted("prompt", f"Panel {idx} contradicts final episode decision")
        effective_panel["scenario_type"] = (decision.get("scenario_type")
                                            or panel.get("scenario_type")
                                            or episode_script.get("scenario_type"))
        effective_panel["_action_mode"] = decision.get("action_mode")
        prompt_text = build_panel_prompt(
            effective_panel,
            ref_paths,
            battle_outcome=battle_outcome or episode_script.get("battle_outcome"),
            performance_spec=specs_by_idx.get(idx),
        )
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
