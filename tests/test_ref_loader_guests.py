"""2026-09-04 결함 6 회귀: 게스트 캐릭터 REF 로드 검증, 비정상 ID는 차단."""

import pytest

from engine.common.exceptions import UnknownCharacterError
from engine.image.ref_loader import GUEST_CHARACTER_IDS, get_refs_for_panel


def test_guest_character_does_not_crash_step6() -> None:
    assert "SENTINEL_YIELD" in GUEST_CHARACTER_IDS
    refs = get_refs_for_panel(["SENTINEL_YIELD", "CRYPTO_SHADE"])
    assert [p.name for p in refs] == ["guest_sentinel_yield.jpg", "guest_crypto_shade.jpg"]


def test_unknown_non_guest_id_still_fatal() -> None:
    with pytest.raises(UnknownCharacterError):
        get_refs_for_panel(["TOTALLY_FAKE_ID"])
