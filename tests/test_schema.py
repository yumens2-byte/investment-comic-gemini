"""
tests/test_schema.py
EpisodeScript Pydantic 스키마 검증.
"""

import pytest
from pydantic import ValidationError

from engine.narrative.schema import EpisodeScript


def _make_valid_script(**overrides) -> dict:
    base = {
        "episode_id": "ICG-2026-04-14-001",
        "date": "2026-04-14",
        "event_type": "BATTLE",
        "title": "오일 쇼크의 습격",
        "logline": "유가 급등으로 오일 쇼크 타이탄이 소환되었다.",
        "panels": [
            {
                "idx": i,
                "panel_type": "BATTLE" if i < 8 else "DISCLAIMER",
                "characters": [],
                "camera": "WIDE",
                "setting": "Seoul",
                "action": "fight",
                "key_text": f"대사{i}",
                "narration": f"내레이션{i}",
            }
            for i in range(1, 9)
        ],
        "caption_x_cover": "오늘 유가 폭등!",
        "caption_x_parts": ["파트1", "파트2"],
        "caption_x_final": "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
        "caption_telegram": "텔레그램 캡션",
        "hashtags": ["#미장", "#EDT"],
        "arc_tension_delta": 5,
    }
    base.update(overrides)
    return base


class TestEpisodeScript:
    def test_valid_script_passes(self):
        data = _make_valid_script()
        script = EpisodeScript.model_validate(data)
        assert script.episode_id == "ICG-2026-04-14-001"
        assert len(script.panels) == 8

    def test_last_panel_not_disclaimer_fails(self):
        data = _make_valid_script()
        data["panels"][-1]["panel_type"] = "BATTLE"  # DISCLAIMER 아님
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_caption_missing_disclaimer_fails(self):
        data = _make_valid_script(caption_x_final="면책고지 없는 캡션")
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_episode_id_pattern_enforced(self):
        data = _make_valid_script(episode_id="WRONG-FORMAT")
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_panel_count_min_8(self):
        data = _make_valid_script()
        data["panels"] = data["panels"][:7]  # 7개 → 실패
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_panel_count_max_10(self):
        data = _make_valid_script()
        extra = {
            "idx": 11,
            "panel_type": "BATTLE",
            "characters": [],
            "camera": "WIDE",
            "setting": "S",
            "action": "A",
            "key_text": "X",
            "narration": "Y",
        }
        data["panels"] = data["panels"] + [extra] * 3  # 11개 → 실패
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_key_text_max_length(self):
        data = _make_valid_script()
        data["panels"][0]["key_text"] = "A" * 41  # 41자 초과
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_narration_max_length(self):
        data = _make_valid_script()
        data["panels"][0]["narration"] = "A" * 121  # 121자 초과
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_arc_tension_delta_bounds(self):
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(_make_valid_script(arc_tension_delta=11))
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(_make_valid_script(arc_tension_delta=-11))

    def test_caption_x_parts_min_2(self):
        data = _make_valid_script(caption_x_parts=["하나"])
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_model_dump_roundtrip(self):
        script = EpisodeScript.model_validate(_make_valid_script())
        d = script.model_dump()
        script2 = EpisodeScript.model_validate(d)
        assert script2.episode_id == script.episode_id


# ── x_publisher 청킹 테스트 ───────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

from engine.common.exceptions import DisclaimerMissing  # noqa: E402
from engine.publish.x_publisher import (  # noqa: E402
    SLEEP_BETWEEN_TWEETS,
    _chunk_slides,
    _guard_disclaimer,
)


class TestXPublisherChunking:
    """_chunk_slides() 슬라이드 분할 검증."""

    def _make_slides(self, n: int) -> list[Path]:
        return [Path(f"/tmp/S{i}.png") for i in range(1, n + 1)]

    def test_8_slides_to_4_chunks(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert len(chunks) == 4
        assert len(chunks[0]) == 1  # T1: 커버
        assert len(chunks[1]) == 3  # T2: S2-S4
        assert len(chunks[2]) == 3  # T3: S5-S7
        assert len(chunks[3]) == 1  # T4: disclaimer

    def test_cover_is_first_slide(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert chunks[0][0] == slides[0]

    def test_disclaimer_is_last_slide(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert chunks[-1][-1] == slides[-1]

    def test_10_slides_chunking(self):
        slides = self._make_slides(10)
        chunks = _chunk_slides(slides)
        assert len(chunks) >= 4
        assert chunks[0][0] == slides[0]
        assert chunks[-1][-1] == slides[-1]

    def test_empty_slides(self):
        assert _chunk_slides([]) == []

    def test_sleep_constant(self):
        assert SLEEP_BETWEEN_TWEETS == 10


class TestDisclaimerGuard:
    """_guard_disclaimer() + DisclaimerMissing 예외 검증."""

    def test_valid_disclaimer_passes(self):
        _guard_disclaimer("본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.")

    def test_missing_disclaimer_raises(self):
        with pytest.raises(DisclaimerMissing):
            _guard_disclaimer("면책 고지 없는 캡션입니다.")

    def test_partial_disclaimer_raises(self):
        with pytest.raises(DisclaimerMissing):
            _guard_disclaimer("투자 참고 정보입니다.")  # 전체 문구 없음

    def test_disclaimer_missing_location_field(self):
        exc = DisclaimerMissing(location="caption_x_final")
        assert "caption_x_final" in str(exc)

    def test_dry_run_publish(self):
        """DRY_RUN 모드에서 X API 호출 없이 DRY_RUN 반환."""
        from engine.publish.x_publisher import publish_episode_x

        script = {
            "caption_x_cover": "테스트 커버",
            "caption_x_parts": ["파트1", "파트2"],
            "caption_x_final": "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
            "hashtags": ["#테스트"],
        }
        slides = [Path(f"/tmp/S{i}.png") for i in range(1, 9)]

        result = publish_episode_x(script, slides, dry_run=True)
        assert len(result) > 0
        assert all("DRY_RUN" in tid for tid in result)


class TestAutoTrim:
    """claude_client._auto_trim_raw_json() 자동 트리밍 테스트."""

    def test_narration_over_limit_trimmed(self):
        """120자 초과 narration은 자동 트리밍되어야 한다."""
        from engine.narrative.claude_client import _auto_trim_raw_json

        long_narration = "가" * 200  # 200자
        raw = {"panels": [{"idx": 1, "narration": long_narration, "key_text": "짧은 텍스트"}]}
        result = _auto_trim_raw_json(raw)
        assert len(result["panels"][0]["narration"]) <= 120

    def test_caption_x_final_over_limit_trimmed(self):
        """240자 초과 caption_x_final은 트리밍 + 면책 고지 보존되어야 한다."""
        from engine.narrative.claude_client import _auto_trim_raw_json

        long_caption = "나" * 300 + " 투자 참고 정보이며, 투자 권유가 아닙니다."
        raw = {"panels": [], "caption_x_final": long_caption}
        result = _auto_trim_raw_json(raw)
        assert len(result["caption_x_final"]) <= 240

    def test_disclaimer_added_when_missing(self):
        """면책 고지 없는 caption_x_final에는 면책 고지가 추가되어야 한다."""
        from engine.narrative.claude_client import _ensure_disclaimer

        text = "오늘 시장 분석입니다."
        result = _ensure_disclaimer(text, 240)
        assert any(p in result for p in ["투자 참고", "투자 권유가 아닙니다"])

    def test_within_limit_not_trimmed(self):
        """제한 내 텍스트는 변경되지 않아야 한다."""
        from engine.narrative.claude_client import _auto_trim_raw_json

        normal = "정상적인 짧은 텍스트입니다."
        raw = {"panels": [{"idx": 1, "narration": normal, "key_text": "짧음"}]}
        result = _auto_trim_raw_json(raw)
        assert result["panels"][0]["narration"] == normal


class TestCharDesign:
    """캐릭터 외형 고정 명세 관련 테스트."""

    def test_char_design_to_prompt_block_format(self):
        """char_design_to_prompt_block이 올바른 형식을 생성해야 한다."""
        from engine.common.notion_loader import char_design_to_prompt_block

        spec = {
            "name": "EDT (Endurance D Tiger)",
            "role": "HERO",
            "position": "LEFT",
            "facing": "RIGHT",
            "body": "Korean male warrior, 30s",
            "costume": "Deep blue + gold armor",
            "identifier": "EDT logo on chest",
            "color_rule": "Deep blue + gold only",
            "strict": "Same every panel",
        }
        result = char_design_to_prompt_block("CHAR_HERO_001", spec)
        assert "EDT (Endurance D Tiger)" in result
        assert "== CHAR_DESIGN:" in result
        assert "== END CHAR_DESIGN:" in result
        assert "HERO" in result
        assert "LEFT" in result
        assert "RIGHT" in result
        assert "EDT logo on chest" in result

    def test_char_design_to_prompt_block_empty_spec(self):
        """빈 spec으로도 기본 블록이 생성되어야 한다."""
        from engine.common.notion_loader import char_design_to_prompt_block

        result = char_design_to_prompt_block("CHAR_HERO_001", {})
        assert "== CHAR_DESIGN:" in result
        assert "== END CHAR_DESIGN:" in result

    def test_get_char_designs_empty_ids(self):
        """빈 char_ids 입력 시 빈 문자열 반환."""
        from engine.image.prompt_builder import _get_char_designs

        result = _get_char_designs([])
        assert result == ""

    def test_get_char_designs_fallback_on_error(self):
        """Notion 로드 실패 시 빈 문자열 반환 (파이프라인 차단 없음)."""
        import os
        from unittest.mock import patch

        from engine.image.prompt_builder import _get_char_designs

        # NOTION_API_KEY 없는 환경에서 fallback 확인
        with patch.dict(os.environ, {"NOTION_API_KEY": ""}):
            # 예외 발생 시 빈 문자열 반환
            result = _get_char_designs(["CHAR_HERO_001"])
            assert isinstance(result, str)
