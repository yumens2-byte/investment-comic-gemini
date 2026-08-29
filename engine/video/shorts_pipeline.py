"""
engine/video/shorts_pipeline.py
Daily Battle Shorts — 게이트 판정 + 쇼츠 각색(ShortsScenario) 파이프라인.

설계 근거 (Notion: ICG Daily Battle Shorts 요구사항 정의서 & 상세설계 v1.0):
  - R2: 기존 이미지 트랙 산출물(icg.episode_assets / icg.daily_analysis)을
        읽기 전용으로 재사용. 승패/시나리오/캐릭터 재계산 금지.
  - R3: 메이저 이벤트 AND 배틀 존재(scenario_type != NO_BATTLE) 시에만 영상 생성.
        메이저 판정은 scripts.run_publish.is_major_event 를 import 재사용 (복제 금지).
  - Strict Isolation: 이미지 트랙 코드/DB 무변경. 본 모듈은 읽기 + video_assets 쓰기만.

Claude 각색 원칙:
  - 8패널 EpisodeScript → 인트로/3컷/아웃트로 쇼츠 시나리오로 "각색"만 수행.
  - Immutable Facts(승패·시나리오·캐릭터)는 프롬프트에 강제 주입하고,
    응답이 이를 위반하면 Consistency Guard 가 ValidationError 로 차단한다.

DRY_RUN 규약(공통 지침서): os.environ.get("DRY_RUN", "true").lower() == "true"
비용 로그: 생성 1회당 cost=$N.NNNN 로그 (gemini_client / veo_client 와 동일 스타일).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

VERSION = "1.1.0"
logger = logging.getLogger(__name__)

# claude_client._MODEL_PRIMARY 와 동일 값 (내부 상수 직접 import 는 결합도 회피)
_MODEL = "claude-sonnet-4-6"
_MAX_RETRIES = 2
_SYSTEM_PROMPT = (
    "당신은 투자 코믹 유니버스 'ICG'의 영상 각색 작가다. "
    "주어진 원본 만화 스크립트의 사실관계·승패·등장인물을 절대 변경하지 않고, "
    "세로형 숏폼 영상 시나리오로만 각색한다. 항상 유효한 JSON 하나만 출력한다."
)

# ── 나레이션 길이 제한 (2026-08-29 run #33229690192 회고) ────────────
# 한국어 TTS 실측 발화 속도 ≈ 5.5자/초. 슬롯을 넘으면 다음 구간과 겹친다.
# 여유 10%를 둔 5자/초 기준으로 스키마에서 강제한다.
CHARS_PER_SEC = 5
# 북엔드는 조립 단계에서 3~6초로 가변 확장되므로 6초(30자)까지 허용한다.
# (아웃트로는 면책 문구가 필수라 3초/15자로는 물리적으로 부족 — 실측 회고 반영)
BOOKEND_NARRATION_MAX = 30
BOOKEND_MIN_SEC = 3
BOOKEND_MAX_SEC = 6
CUT_NARRATION_MAX = 40  # 8초 슬롯 기준

# Veo 3.1 fast preview 제약: 컷당 4/6/8초 (engine/video/veo_client.py 실측)
ALLOWED_CUT_DURATIONS = (4, 6, 8)
DEFAULT_CUT_DURATION = 8
BOOKEND_DURATION_SEC = 3  # 인트로/아웃트로 기본 노출 시간 (나레이션 길이로 가변 확장)


class ShortsPipelineError(Exception):
    """게이트/각색 파이프라인 실패."""


class ConsistencyGuardError(ShortsPipelineError):
    """각색 결과가 Immutable Facts 와 불일치."""


class CanonGuardError(ShortsPipelineError):
    """video_prompt 에 Canon 캐릭터 외형 지시가 누락됨."""


def _is_dry_run(dry_run: Optional[bool] = None) -> bool:
    if dry_run is not None:
        return dry_run
    return os.environ.get("DRY_RUN", "true").lower() == "true"


def build_shorts_episode_id(episode_date: str) -> str:
    """
    쇼츠 episode_id 채번 — scripts/run_video_trailer._get_episode_id 와 동일 규칙.

    Format: icg-v-YYYY-MM-DD-001 (일 1편 고정, video_assets PK).
    """
    return f"icg-v-{episode_date}-001"


# ────────────────────────────────────────────────────────
# DB 로더 (테스트에서 monkeypatch 대상 — 분리 유지)
# ────────────────────────────────────────────────────────


def _load_latest_episode_row(episode_date: str) -> dict | None:
    """episode_assets 에서 해당일 최신 에피소드 행 조회 (episode_no DESC)."""
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .order("episode_no", desc=True)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    return rows.data[0]


def _load_analysis_row(episode_date: str) -> dict | None:
    """daily_analysis 에서 캐릭터 선정 결과(selected_hero_id 등) 조회."""
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_analysis")
        .select("scenario_type, selected_hero_id, selected_villain_id, ending_tone")
        .eq("analysis_date", episode_date)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    return rows.data[0]


def _load_video_asset_row(episode_id: str) -> dict | None:
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("video_assets")
        .select("episode_id, status, youtube_video_id")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    return rows.data[0]


# ────────────────────────────────────────────────────────
# STEP S1 — 게이트 판정
# ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateResult:
    """메이저+배틀 게이트 판정 결과."""

    passed: bool
    reason: str
    episode_date: str
    episode_id: str
    event_type: str = ""
    scenario_type: str = ""
    episode_row: dict | None = field(default=None, compare=False)
    analysis_row: dict | None = field(default=None, compare=False)

    def to_json(self) -> dict:
        payload = asdict(self)
        # DB 저장 시 원본 row 전체는 제외 (episode_assets 에 이미 존재 — 중복 저장 방지)
        payload.pop("episode_row", None)
        payload.pop("analysis_row", None)
        return payload


def run_gate(episode_date: str) -> GateResult:
    """
    영상 생성 게이트 3단 판정:
      1) episode_assets 행 + script_json 존재 (STEP 5 Persist 완료)
      2) 메이저 이벤트 — run_publish.is_major_event 재사용
      3) 배틀 존재 — scenario_type != "NO_BATTLE"
      + 멱등: 동일 episode_id 가 이미 published 면 차단.
    """
    from scripts.run_publish import is_major_event  # 판정 기준 단일 소스 (복제 금지)

    episode_id = build_shorts_episode_id(episode_date)
    logger.info(
        "[shorts_pipeline] v%s gate start: date=%s episode_id=%s",
        VERSION,
        episode_date,
        episode_id,
    )

    existing = _load_video_asset_row(episode_id)
    if existing and (existing.get("status") == "published" or existing.get("youtube_video_id")):
        return GateResult(
            passed=False,
            reason="already_published",
            episode_date=episode_date,
            episode_id=episode_id,
        )

    row = _load_latest_episode_row(episode_date)
    if row is None:
        return GateResult(
            passed=False,
            reason="episode_assets_not_found",
            episode_date=episode_date,
            episode_id=episode_id,
        )
    if not row.get("script_json"):
        return GateResult(
            passed=False,
            reason="script_json_missing",
            episode_date=episode_date,
            episode_id=episode_id,
            event_type=str(row.get("event_type") or ""),
            scenario_type=str(row.get("scenario_type") or ""),
        )

    event_type = str(row.get("event_type") or "")
    scenario_type = str(row.get("scenario_type") or "")

    if not is_major_event(event_type):
        return GateResult(
            passed=False,
            reason=f"non_major_event:{event_type}",
            episode_date=episode_date,
            episode_id=episode_id,
            event_type=event_type,
            scenario_type=scenario_type,
        )

    if scenario_type.upper() == "NO_BATTLE":
        return GateResult(
            passed=False,
            reason="no_battle_scenario",
            episode_date=episode_date,
            episode_id=episode_id,
            event_type=event_type,
            scenario_type=scenario_type,
        )

    analysis = _load_analysis_row(episode_date)
    result = GateResult(
        passed=True,
        reason="major_battle",
        episode_date=episode_date,
        episode_id=episode_id,
        event_type=event_type,
        scenario_type=scenario_type,
        episode_row=row,
        analysis_row=analysis,
    )
    logger.info(
        "[shorts_pipeline] gate PASS: event_type=%s scenario=%s",
        event_type,
        scenario_type,
    )
    return result


# ────────────────────────────────────────────────────────
# STEP S2 — ShortsScenario 스키마
# ────────────────────────────────────────────────────────


class ShortsCut(BaseModel):
    """본편 영상 1컷 (Veo 생성 단위)."""

    seq: int = Field(ge=1, le=3)
    caption: str = Field(min_length=1, max_length=60)
    # 8초 슬롯 × 5자/초 — 초과 시 나레이션이 다음 컷과 겹친다 (v1.1.0 강제)
    narration_tts: str = Field(min_length=1, max_length=CUT_NARRATION_MAX)
    video_prompt: str = Field(min_length=20)
    duration_sec: Literal[4, 6, 8] = DEFAULT_CUT_DURATION


class ShortsBookend(BaseModel):
    """인트로/아웃트로 정지 이미지."""

    caption: str = Field(min_length=1, max_length=60)
    # 3초 슬롯 기준. 초과분은 조립 단계에서 북엔드 길이를 늘려 흡수한다.
    narration_tts: str = Field(min_length=1, max_length=BOOKEND_NARRATION_MAX)
    image_prompt: str = Field(min_length=20)


class ShortsScenario(BaseModel):
    """일일 배틀 쇼츠 각색 결과 (video_assets.shorts_scenario_json 저장 단위)."""

    episode_id: str
    episode_date: str
    event_type: str
    scenario_type: str
    outcome: str
    hero_ids: list[str] = Field(min_length=1)
    villain_id: str
    intro: ShortsBookend
    cuts: list[ShortsCut] = Field(min_length=3, max_length=3)
    outro: ShortsBookend
    youtube_title: str = Field(min_length=1, max_length=100)
    youtube_description: str = Field(min_length=1, max_length=4500)

    @model_validator(mode="after")
    def validate_cut_sequence(self) -> "ShortsScenario":
        seqs = [c.seq for c in self.cuts]
        if seqs != [1, 2, 3]:
            raise ValueError(f"cuts seq must be [1,2,3] in order. got={seqs}")
        return self

    def total_duration_sec(self) -> int:
        """총 길이 = 3컷 + 가변 북엔드 2개 (나레이션 길이 기반)."""
        import math as _math

        def _bookend(text: str) -> int:
            needed = _math.ceil(len(text) / CHARS_PER_SEC)
            return max(BOOKEND_MIN_SEC, min(BOOKEND_MAX_SEC, needed))

        return (
            sum(c.duration_sec for c in self.cuts)
            + _bookend(self.intro.narration_tts)
            + _bookend(self.outro.narration_tts)
        )


def enforce_consistency(
    scenario: ShortsScenario,
    *,
    outcome: str,
    hero_ids: list[str],
    villain_id: str,
) -> None:
    """
    Consistency Guard — 각색 결과가 이미지 트랙 확정값과 불일치하면 차단.
    (이미지/영상 트랙 간 승패·캐스팅 어긋남 방지 — 상세설계 3.2)
    """
    if scenario.outcome != outcome:
        raise ConsistencyGuardError(
            f"outcome mismatch: expected={outcome} got={scenario.outcome}"
        )
    if sorted(scenario.hero_ids) != sorted(hero_ids):
        raise ConsistencyGuardError(
            f"hero_ids mismatch: expected={hero_ids} got={scenario.hero_ids}"
        )
    if scenario.villain_id != villain_id:
        raise ConsistencyGuardError(
            f"villain_id mismatch: expected={villain_id} got={scenario.villain_id}"
        )


# ────────────────────────────────────────────────────────
# STEP S2 — Claude 각색 호출
# ────────────────────────────────────────────────────────


CANON_PATH = Path("config/characters.yaml")

# Canon Guard: 캐릭터별 필수 시각 키워드 (video_prompt 에 반드시 등장)
# 근거: config/characters.yaml forms[].description / villains[].description 실측
CANON_VISUAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "CHAR_HERO_001": ("chainsaw", "blue bodysuit", "d emblem"),
    "CHAR_HERO_003": ("flame hair", "shirtless"),
    "CHAR_VILLAIN_004": ("hydra", "five", "serpent"),
}


def _load_canon() -> dict:
    """config/characters.yaml 로드 (실패 시 빈 dict — 각색은 계속 진행)."""
    try:
        import yaml

        if not CANON_PATH.exists():
            logger.warning("[shorts_pipeline] canon 파일 없음: %s", CANON_PATH)
            return {}
        return yaml.safe_load(CANON_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("[shorts_pipeline] canon 로드 실패 (무시): %s", exc)
        return {}


def build_canon_visual_block(char_ids: list[str]) -> str:
    """
    Veo 프롬프트용 Canon 외형 지시문 생성.

    Veo T2V 는 참조 이미지를 받지 못하므로(veo_client 실측), 캐릭터 일관성은
    텍스트 프롬프트로만 강제할 수 있다. characters.yaml 의 forms description /
    villain description / canon_prompts / style_lock 을 조합한다.
    기존 이미지 트랙(prompt_builder._get_local_canon_designs)과 동일 데이터 소스.
    """
    canon = _load_canon()
    if not canon:
        return ""

    heroes = canon.get("heroes", {}) or {}
    villains = canon.get("villains", {}) or {}
    blocks: list[str] = []

    for cid in char_ids:
        entry = heroes.get(cid) or villains.get(cid) or {}
        if not entry:
            logger.warning("[shorts_pipeline] canon 미등록 캐릭터: %s", cid)
            continue
        name = entry.get("name_en") or entry.get("name_ko") or cid
        lines = [f"- {name} ({cid}):"]

        if cid in heroes:
            form_key = entry.get("default_form") or "form0"
            form = (entry.get("forms") or {}).get(form_key) or {}
            desc = form.get("description") or ""
            if desc:
                lines.append(f"    외형({form_key}): {desc}")
        else:
            if entry.get("description"):
                lines.append(f"    외형: {entry['description']}")

        keywords = CANON_VISUAL_KEYWORDS.get(cid)
        if keywords:
            lines.append(
                "    video_prompt 필수 영어 키워드(축어 포함): " + ", ".join(keywords)
            )
        blocks.append("\n".join(lines))

    if not blocks:
        return ""

    style = canon.get("style_lock", {}) or {}
    style_line = ", ".join(f"{k}={v}" for k, v in style.items())
    return (
        "[CANON 캐릭터 외형 — 반드시 준수]\n"
        + "\n".join(blocks)
        + (f"\n[STYLE LOCK] {style_line}" if style_line else "")
    )


def enforce_canon_visuals(scenario: "ShortsScenario") -> None:
    """
    Canon Guard — 각 컷의 video_prompt 에 등장 캐릭터의 필수 시각 키워드가
    포함되었는지 검사한다. 미포함 시 Veo 가 임의 캐릭터를 생성하므로 차단한다.
    (2026-08-29 run #33229690192: 'battle armor' 만 기술되어 비Canon 히어로 생성)
    """
    all_prompts = " ".join(c.video_prompt for c in scenario.cuts).lower()
    missing: list[str] = []

    for cid in [*scenario.hero_ids, scenario.villain_id]:
        keywords = CANON_VISUAL_KEYWORDS.get(cid)
        if not keywords:
            continue  # 키워드 미정의 캐릭터는 검사 제외 (오탐 방지)
        if not any(kw in all_prompts for kw in keywords):
            missing.append(f"{cid}(필요: {'/'.join(keywords)})")

    if missing:
        raise CanonGuardError(
            "video_prompt 에 Canon 외형 키워드 누락: " + ", ".join(missing)
        )

    # ALLIANCE 는 히어로 전원이 최소 1컷에 등장해야 한다.
    if scenario.scenario_type.upper() == "ALLIANCE" and len(scenario.hero_ids) > 1:
        for cid in scenario.hero_ids:
            keywords = CANON_VISUAL_KEYWORDS.get(cid)
            if keywords and not any(kw in all_prompts for kw in keywords):
                raise CanonGuardError(f"ALLIANCE 인데 {cid} 가 컷에 등장하지 않음")


def _extract_json(text: str) -> str:
    """응답에서 JSON 본문만 추출 (```json 펜스 허용)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ShortsPipelineError("Claude 응답에서 JSON 을 찾지 못함")
    return stripped[start : end + 1]


def extract_immutable_facts(gate: GateResult) -> dict:
    """episode_assets / daily_analysis 행에서 불변 사실 추출."""
    row = gate.episode_row or {}
    analysis = gate.analysis_row or {}

    battle = row.get("battle_json") or {}
    if isinstance(battle, str):
        battle = json.loads(battle)
    outcome = str(battle.get("outcome") or "")

    heroes = row.get("heroes_json") or []
    if isinstance(heroes, str):
        heroes = json.loads(heroes)
    if not heroes and analysis.get("selected_hero_id"):
        heroes = [analysis["selected_hero_id"]]

    villain_id = str(
        battle.get("villain_id") or analysis.get("selected_villain_id") or ""
    )

    if not outcome or not heroes or not villain_id:
        raise ShortsPipelineError(
            f"Immutable Facts 불완전: outcome={outcome!r} heroes={heroes!r} "
            f"villain={villain_id!r} — episode_assets/daily_analysis 확인 필요"
        )

    return {
        "episode_id": gate.episode_id,
        "episode_date": gate.episode_date,
        "event_type": gate.event_type,
        "scenario_type": gate.scenario_type,
        "outcome": outcome,
        "hero_ids": [str(h) for h in heroes],
        "villain_id": villain_id,
        "ending_tone": str(analysis.get("ending_tone") or "TENSE"),
    }


def _build_adaptation_prompt(facts: dict, script_json: dict) -> str:
    """8패널 스크립트 → 쇼츠 각색 사용자 프롬프트 (Immutable Facts + Canon 강제 주입)."""
    schema_hint = {
        "episode_id": facts["episode_id"],
        "episode_date": facts["episode_date"],
        "event_type": facts["event_type"],
        "scenario_type": facts["scenario_type"],
        "outcome": facts["outcome"],
        "hero_ids": facts["hero_ids"],
        "villain_id": facts["villain_id"],
        "intro": {"caption": "...", "narration_tts": "...", "image_prompt": "..."},
        "cuts": [
            {
                "seq": 1,
                "caption": "...",
                "narration_tts": "...",
                "video_prompt": "...",
                "duration_sec": 8,
            }
        ],
        "outro": {"caption": "...", "narration_tts": "...", "image_prompt": "..."},
        "youtube_title": "...",
        "youtube_description": "...",
    }
    canon_block = build_canon_visual_block([*facts["hero_ids"], facts["villain_id"]])
    return (
        "당신은 투자 코믹 유니버스의 영상 각색 작가다. 아래 [원본 8패널 스크립트]를 "
        "약 30초 세로형 YouTube Shorts 시나리오(인트로 이미지 1 + 8초 영상 3컷 + 아웃트로 이미지 1)로 "
        "각색하라.\n\n"
        "[IMMUTABLE FACTS — 절대 변경 금지]\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        f"{canon_block}\n\n"
        "[각색 규칙]\n"
        "1. outcome / hero_ids / villain_id / scenario_type 은 위 값을 그대로 출력 JSON 에 복사한다.\n"
        "2. 승패·전개 방향을 원본과 다르게 창작하지 않는다. 시장 수치는 원본 스크립트에 있는 값만 사용한다.\n"
        "3. cuts 는 정확히 3개 (seq 1,2,3 / duration_sec 8 고정). video_prompt 는 영어, "
        "cinematic vertical 9:16, Manhwa style 로 작성한다.\n"
        "4. **[CANON 캐릭터 외형]의 필수 영어 키워드를 각 video_prompt 에 축어로 반드시 포함**한다. "
        "영상 생성기는 참조 이미지를 받지 못하므로, 외형을 글로 쓰지 않으면 전혀 다른 캐릭터가 만들어진다. "
        "hero_ids 가 2명 이상이면(ALLIANCE) 전원이 최소 1컷 이상에 등장해야 한다.\n"
        "5. caption / narration_tts 는 한국어. **narration_tts 글자 수 상한을 절대 넘기지 마라: "
        f"cuts 는 각 {CUT_NARRATION_MAX}자 이내, intro/outro 는 각 {BOOKEND_NARRATION_MAX}자 이내** "
        "(초과하면 음성이 다음 장면과 겹친다). 공백·문장부호 포함으로 센다.\n"
        "6. intro.image_prompt / outro.image_prompt 는 영어 정지 이미지 프롬프트 (vertical 9:16). "
        "여기에도 등장 캐릭터의 Canon 외형 키워드를 포함한다.\n"
        f"7. outro 의 narration_tts 에 '투자 참고, 투자 권유 아님' 취지를 "
        f"{BOOKEND_NARRATION_MAX}자 이내로 압축해 넣는다.\n"
        "8. youtube_title 은 한국어 60자 이내 후킹형(과장 금지). youtube_description 은 면책 문구 포함.\n"
        "9. 출력은 아래 구조의 JSON 하나만. 마크다운/설명/백틱 금지.\n\n"
        "[출력 JSON 구조]\n"
        f"{json.dumps(schema_hint, ensure_ascii=False, indent=2)}\n\n"
        "[원본 8패널 스크립트]\n"
        f"{json.dumps(script_json, ensure_ascii=False)}"
    )


def generate_shorts_scenario(
    gate: GateResult,
    dry_run: Optional[bool] = None,
) -> tuple[Optional[ShortsScenario], float]:
    """
    Claude 각색 실행.

    Returns:
        (ShortsScenario | None, cost_usd)
        DRY_RUN 이면 (None, 0.0) — Claude 미호출 (비용 0).
    """
    if not gate.passed or gate.episode_row is None:
        raise ShortsPipelineError(f"gate 미통과 상태에서 각색 호출: reason={gate.reason}")

    facts = extract_immutable_facts(gate)
    script_json = gate.episode_row.get("script_json") or {}
    if isinstance(script_json, str):
        script_json = json.loads(script_json)

    if _is_dry_run(dry_run):
        logger.info(
            "[shorts_pipeline] DRY_RUN — Claude 각색 스킵 (episode_id=%s, facts=%s)",
            gate.episode_id,
            {k: facts[k] for k in ("event_type", "scenario_type", "outcome", "villain_id")},
        )
        return None, 0.0

    from anthropic import Anthropic

    from engine.narrative.claude_client import (
        _build_messages_create_kwargs,
        estimate_cost,
    )

    prompt = _build_adaptation_prompt(facts, script_json)
    client = Anthropic()

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 2):
        start = time.monotonic()
        # SDK 호환: Anthropic Python SDK 1.0 은 top-level temperature 를 제거했다.
        # 기존 이미지 트랙과 동일한 단일 소스 헬퍼를 재사용한다 (중복 구현 금지).
        create_kwargs = _build_messages_create_kwargs(
            client.messages.create,
            model=_MODEL,
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        response = client.messages.create(**create_kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        cost = estimate_cost(
            response.usage.input_tokens, response.usage.output_tokens, model=_MODEL
        )
        try:
            data = json.loads(_extract_json(raw_text))
            scenario = ShortsScenario(**data)
            enforce_consistency(
                scenario,
                outcome=facts["outcome"],
                hero_ids=facts["hero_ids"],
                villain_id=facts["villain_id"],
            )
            enforce_canon_visuals(scenario)
            # 생성당 비용 로그 — gemini/veo 클라이언트와 동일 스타일
            logger.info(
                "[shorts_pipeline] 각색 완료: episode_id=%s attempt=%d "
                "elapsed=%dms input=%d output=%d cost=$%.4f",
                gate.episode_id,
                attempt,
                elapsed_ms,
                response.usage.input_tokens,
                response.usage.output_tokens,
                cost,
            )
            return scenario, cost
        except (
            json.JSONDecodeError,
            ValueError,
            ConsistencyGuardError,
            CanonGuardError,
        ) as exc:
            last_error = exc
            logger.warning(
                "[shorts_pipeline] 각색 검증 실패 attempt=%d/%d cost=$%.4f: %s",
                attempt,
                _MAX_RETRIES + 1,
                cost,
                exc,
            )
            prompt = (
                f"{prompt}\n\n[재시도 피드백]\n이전 응답이 검증에 실패했다: {exc}\n"
                "IMMUTABLE FACTS 값을 그대로 복사하고, 출력 JSON 구조를 정확히 지켜 다시 생성하라."
            )

    raise ShortsPipelineError(
        f"각색 {_MAX_RETRIES + 1}회 실패: episode_id={gate.episode_id} last={last_error}"
    )


# ────────────────────────────────────────────────────────
# 저장 (video_assets)
# ────────────────────────────────────────────────────────


def persist_gate_result(gate: GateResult) -> str:
    """
    게이트 결과를 icg.video_assets 에 upsert (PK: episode_id).

    Returns:
        저장된 status ("skipped" | "gated")
    """
    from engine.common.supabase_client import icg_table

    status = "gated" if gate.passed else "skipped"
    existing = _load_video_asset_row(gate.episode_id)
    if existing and existing.get("status") not in (None, "", "skipped", "gated"):
        # 이후 단계(scenario_ready~published) 진행 중 행은 게이트 재기록으로 덮지 않음
        logger.info(
            "[shorts_pipeline] persist_gate_result skip — status=%s 유지",
            existing.get("status"),
        )
        return str(existing.get("status"))

    icg_table("video_assets").upsert(
        {
            "episode_id": gate.episode_id,
            "episode_date": gate.episode_date,
            "scenario_type": gate.scenario_type or None,
            "status": status,
            "gate_result_json": gate.to_json(),
        },
        on_conflict="episode_id",
    ).execute()
    logger.info(
        "[shorts_pipeline] gate 저장: episode_id=%s status=%s reason=%s",
        gate.episode_id,
        status,
        gate.reason,
    )
    return status


def load_scenario(episode_id: str) -> Optional[ShortsScenario]:
    """video_assets.shorts_scenario_json 에서 각색 결과 복원 (S3~S5 stage 독립 실행용)."""
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("video_assets")
        .select("shorts_scenario_json")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    payload = rows.data[0].get("shorts_scenario_json")
    if not payload:
        return None
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ShortsScenario(**payload)


def persist_scenario(gate: GateResult, scenario: ShortsScenario) -> None:
    """각색 결과 저장 → status='scenario_ready'."""
    from engine.common.supabase_client import icg_table

    icg_table("video_assets").upsert(
        {
            "episode_id": gate.episode_id,
            "episode_date": gate.episode_date,
            "scenario_type": gate.scenario_type or None,
            "status": "scenario_ready",
            "gate_result_json": gate.to_json(),
            "shorts_scenario_json": scenario.model_dump(),
        },
        on_conflict="episode_id",
    ).execute()
    logger.info(
        "[shorts_pipeline] scenario 저장: episode_id=%s status=scenario_ready "
        "total_duration=%ds",
        gate.episode_id,
        scenario.total_duration_sec(),
    )
