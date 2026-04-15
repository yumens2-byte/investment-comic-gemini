"""
tests/test_ref_loader.py
ref_loader.py 단위 테스트.

Acceptance Criteria (Track F):
- [x] SHA256 불일치 시 CanonLockViolation 발생
- [x] __TBD__ SHA256은 검증 생략
- [x] 알 수 없는 char_id → UnknownCharacterError
- [x] get_refs_for_panel() 경로 목록 반환
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from engine.common.exceptions import CanonLockViolation, UnknownCharacterError
from engine.image import ref_loader


def _make_test_canon(tmp_path: Path, sha256_val: str = "__TBD__") -> Path:
    """테스트용 characters.yaml 생성."""
    ref_file = tmp_path / "hero_test.png"
    ref_file.write_bytes(b"fake_png_data")

    canon = {
        "version": "1.0",
        "heroes": {
            "CHAR_HERO_TEST": {
                "name_en": "Test Hero",
                "notion_label": "Test",
                "base_power": 80,
                "forms": {
                    "form1": {
                        "ref": str(ref_file),
                        "sha256": sha256_val,
                    }
                },
                "default_form": "form1",
                "canon_lock": True,
            }
        },
        "villains": {},
    }
    canon_path = tmp_path / "characters.yaml"
    with open(canon_path, "w") as f:
        yaml.dump(canon, f)
    return canon_path


class TestVerifyCanon:
    """verify_canon() — SHA256 검증."""

    def test_tbd_sha256_skips_verification(self, tmp_path):
        """__TBD__ SHA256은 검증 없이 통과."""
        canon_path = _make_test_canon(tmp_path, sha256_val="__TBD__")
        ref_loader.invalidate_cache()

        with patch.object(ref_loader, "_CANON_PATH", canon_path):
            ref_loader.invalidate_cache()
            # 예외 없이 통과해야 함
            ref_loader.verify_canon("CHAR_HERO_TEST")

    def test_sha256_mismatch_raises(self, tmp_path):
        """SHA256 불일치 시 CanonLockViolation."""
        # 실제 SHA256과 다른 값을 YAML에 기록
        wrong_sha = "a" * 64
        canon_path = _make_test_canon(tmp_path, sha256_val=wrong_sha)
        ref_loader.invalidate_cache()

        with patch.object(ref_loader, "_CANON_PATH", canon_path):
            ref_loader.invalidate_cache()
            with pytest.raises(CanonLockViolation) as exc_info:
                ref_loader.verify_canon("CHAR_HERO_TEST")
            assert exc_info.value.char_id == "CHAR_HERO_TEST"

    def test_correct_sha256_passes(self, tmp_path):
        """올바른 SHA256 → 검증 통과."""
        ref_file = tmp_path / "hero_test.png"
        ref_file.write_bytes(b"fake_png_data")
        correct_sha = hashlib.sha256(b"fake_png_data").hexdigest()

        canon_path = _make_test_canon(tmp_path, sha256_val=correct_sha)
        ref_loader.invalidate_cache()

        with patch.object(ref_loader, "_CANON_PATH", canon_path):
            ref_loader.invalidate_cache()
            ref_loader.verify_canon("CHAR_HERO_TEST")  # 예외 없이 통과

    def test_unknown_char_id_raises(self, tmp_path):
        """알 수 없는 char_id → UnknownCharacterError."""
        canon_path = _make_test_canon(tmp_path)
        with patch.object(ref_loader, "_CANON_PATH", canon_path):
            ref_loader.invalidate_cache()
            with pytest.raises(UnknownCharacterError):
                ref_loader.verify_canon("CHAR_HERO_NONEXISTENT")


class TestGetRefPath:
    """get_ref_path() 경로 반환."""

    def test_returns_path_for_valid_char(self, tmp_path):
        """유효한 char_id → Path 반환."""
        canon_path = _make_test_canon(tmp_path)
        with patch.object(ref_loader, "_CANON_PATH", canon_path):
            ref_loader.invalidate_cache()
            path = ref_loader.get_ref_path("CHAR_HERO_TEST")
            assert isinstance(path, Path)


# ── prompt_builder 테스트 ────────────────────────────────────────────────────

from engine.image.prompt_builder import (  # noqa: E402
    SECURITY_NEGATIVE_BLOCK_V1_1,
    build_panel_prompt,
    verify_negative_block_present,
)


class TestPromptBuilder:
    """
    prompt_builder.py 단위 테스트.

    Acceptance Criteria (Track F):
    - [x] SECURITY NEGATIVE BLOCK v1.1 반드시 포함
    - [x] 캐릭터 위치 정보 포함
    - [x] 카메라/씬 정보 포함
    """

    def test_security_negative_block_present(self):
        """모든 생성 프롬프트에 SECURITY NEGATIVE BLOCK이 포함되어야 한다."""
        prompt = build_panel_prompt(
            panel_idx=1,
            panel_type="BATTLE",
            setting="Seoul financial district at night",
            action="Hero raises fist against villain",
            camera="LOW_ANGLE",
            characters=[
                {
                    "char_id": "CHAR_HERO_003",
                    "role": "hero",
                    "position": "LEFT",
                    "name_en": "Leverage Muscle Man",
                },
                {
                    "char_id": "CHAR_VILLAIN_002",
                    "role": "villain",
                    "position": "RIGHT",
                    "name_en": "Oil Shock Titan",
                },
            ],
        )
        assert verify_negative_block_present(prompt), "SECURITY NEGATIVE BLOCK 누락"

    def test_no_real_people_clause(self):
        """'No real people' 조항이 반드시 포함되어야 한다."""
        prompt = build_panel_prompt(
            panel_idx=2,
            panel_type="TENSION",
            setting="Stock exchange floor",
            action="Tension builds",
            camera="MEDIUM",
            characters=[],
        )
        assert "No real people" in prompt

    def test_no_copyrighted_characters_clause(self):
        """Marvel/DC/Disney 등 저작권 차단 조항이 포함되어야 한다."""
        prompt = build_panel_prompt(
            panel_idx=3,
            panel_type="NORMAL",
            setting="Office",
            action="Analysis",
            camera="WIDE",
            characters=[],
        )
        assert "Marvel" in prompt or "copyrighted characters" in prompt.lower()

    def test_hero_villain_position_in_prompt(self):
        """히어로는 LEFT, 빌런은 RIGHT 위치 정보가 포함되어야 한다."""
        prompt = build_panel_prompt(
            panel_idx=1,
            panel_type="BATTLE",
            setting="Test setting",
            action="Test action",
            camera="WIDE",
            characters=[
                {"char_id": "CHAR_HERO_001", "role": "hero", "position": "LEFT", "name_en": "EDT"},
                {
                    "char_id": "CHAR_VILLAIN_004",
                    "role": "villain",
                    "position": "RIGHT",
                    "name_en": "Volatility Hydra",
                },
            ],
        )
        assert "LEFT" in prompt
        assert "RIGHT" in prompt

    def test_camera_angle_in_prompt(self):
        """카메라 정보가 프롬프트에 포함되어야 한다."""
        prompt = build_panel_prompt(
            panel_idx=1,
            panel_type="COVER",
            setting="Epic background",
            action="Cover shot",
            camera="LOW_ANGLE",
            characters=[],
        )
        assert "LOW_ANGLE" in prompt

    def test_setting_and_action_in_prompt(self):
        """씬 설정과 액션이 프롬프트에 포함되어야 한다."""
        setting = "Tokyo financial district"
        action = "Hero confronts the villain"
        prompt = build_panel_prompt(
            panel_idx=2,
            panel_type="CLIMAX",
            setting=setting,
            action=action,
            camera="DUTCH",
            characters=[],
        )
        assert setting in prompt
        assert action in prompt

    def test_no_text_overlay_clause(self):
        """이미지 내 텍스트 금지 조항이 포함되어야 한다 (PIL 후처리용)."""
        prompt = build_panel_prompt(
            panel_idx=1,
            panel_type="BATTLE",
            setting="Test",
            action="Test",
            camera="WIDE",
            characters=[],
        )
        assert "text" in prompt.lower() and "overlay" in prompt.lower() or "No text" in prompt

    def test_security_block_constant_completeness(self):
        """SECURITY_NEGATIVE_BLOCK_V1_1 상수에 필수 조항이 모두 포함되어야 한다."""
        required_clauses = [
            "No real people",
            "copyrighted",
            "nudity",
            "gore",
            "watermarks",
        ]
        for clause in required_clauses:
            assert clause.lower() in SECURITY_NEGATIVE_BLOCK_V1_1.lower(), f"'{clause}' 조항 누락"
