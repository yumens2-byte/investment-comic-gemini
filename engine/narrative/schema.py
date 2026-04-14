"""
engine/narrative/schema.py
ICG 에피소드 스크립트 Pydantic 스키마.

doc 16a Pipeline Master Spec STEP 4 기반.
Claude API 출력 JSON을 이 스키마로 검증한다.
검증 실패 시 NarrativeValidationError 발생 (최대 2회 재시도).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PanelCharacter(BaseModel):
    """패널 등장 캐릭터."""

    char_id: str = Field(description="characters.yaml 등록 ID (예: CHAR_HERO_003)")
    role: Literal["hero", "villain", "npc"]
    form: str | None = None
    position: Literal["LEFT", "RIGHT", "CENTER"]


class Panel(BaseModel):
    """단일 패널 스크립트."""

    idx: int = Field(ge=1, description="패널 번호 (1-based)")
    panel_type: Literal[
        "COVER",       # 표지
        "TENSION",     # 긴장 고조
        "BATTLE",      # 전투
        "CLIMAX",      # 클라이맥스
        "AFTERMATH",   # 여파
        "TEXT_CARD",   # 텍스트 카드
        "DISCLAIMER",  # 면책 고지 (마지막 패널 필수)
    ]
    characters: list[PanelCharacter] = Field(default_factory=list)
    camera: Literal["WIDE", "MEDIUM", "CLOSE_UP", "DUTCH", "LOW_ANGLE"]
    setting: str = Field(description="배경 묘사 (영문, 40자 이내 권장)")
    action: str = Field(description="액션 묘사 (영문)")
    key_text: str = Field(
        max_length=40,
        description="패널 대사 (한국어, 말풍선 텍스트, 40자 이내)",
    )
    narration: str = Field(
        max_length=120,
        description="내레이션 박스 텍스트 (한국어, 120자 이내)",
    )
    market_ref: str | None = Field(
        default=None,
        description="시장 데이터 참조 (예: 'VIX 24.1 (+32%)')",
    )


class EpisodeScript(BaseModel):
    """ICG 에피소드 전체 스크립트."""

    episode_id: str = Field(
        description="에피소드 ID (예: ICG-2026-04-14-001)",
        pattern=r"^ICG-\d{4}-\d{2}-\d{2}-\d{3}$",
    )
    date: str = Field(description="에피소드 날짜 (YYYY-MM-DD)")
    event_type: str = Field(description="에피소드 타입 (BATTLE/SHOCK/AFTERMATH/INTEL/NORMAL)")
    title: str = Field(description="에피소드 제목 (한국어)")
    logline: str = Field(description="한 줄 요약 (한국어, 100자 이내)", max_length=100)

    panels: list[Panel] = Field(
        min_length=8,
        max_length=10,
        description="패널 목록 (8~10개, 마지막은 DISCLAIMER 필수)",
    )

    caption_x_cover: str = Field(
        max_length=240,
        description="X 커버 트윗 캡션 (한국어, 240자 이내)",
    )
    caption_x_parts: list[str] = Field(
        min_length=2,
        max_length=4,
        description="X 스레드 파트 캡션 목록 (2~4개)",
    )
    caption_x_final: str = Field(
        max_length=240,
        description="X 마지막 트윗 (면책 고지 포함 필수, 240자 이내)",
    )
    caption_telegram: str = Field(description="Telegram 전문 발행 캡션 (HTML 허용)")

    hashtags: list[str] = Field(
        description="해시태그 목록 (예: ['#미장', '#EDT', '#투자코믹'])",
    )
    arc_tension_delta: int = Field(
        ge=-10,
        le=10,
        description="이번 에피소드의 긴장도 변화량 (-10 ~ +10)",
    )

    @model_validator(mode="after")
    def validate_disclaimer_and_caption(self) -> "EpisodeScript":
        """
        검증 규칙:
        1. 마지막 패널은 DISCLAIMER 타입이어야 한다.
        2. caption_x_final에 면책 고지 문구가 포함되어야 한다.
        """
        # 마지막 패널 DISCLAIMER 검증
        if self.panels and self.panels[-1].panel_type != "DISCLAIMER":
            raise ValueError(
                f"마지막 패널(idx={self.panels[-1].idx})은 DISCLAIMER 타입이어야 합니다. "
                f"현재: {self.panels[-1].panel_type}"
            )

        # caption_x_final 면책 고지 검증
        disclaimer_phrases = [
            "투자 참고",
            "투자 권유가 아닙니다",
            "투자 권유 아닙니다",
        ]
        has_disclaimer = any(p in self.caption_x_final for p in disclaimer_phrases)
        if not has_disclaimer:
            raise ValueError(
                "caption_x_final에 면책 고지 문구가 없습니다. "
                "'본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다' 포함 필수."
            )

        return self
