"""2026-09-04 결함 6 회귀: 게스트 캐릭터는 REF 없이 통과, 비정상 ID는 차단."""

import pytest

from engine.common.exceptions import UnknownCharacterError
from engine.image.ref_loader import GUEST_CHARACTER_IDS, get_refs_for_panel


def test_guest_character_does_not_crash_step6() -> None:
    assert "SENTINEL_YIELD" in GUEST_CHARACTER_IDS
    # 게스트만으로 구성 — canon 레지스트리 조회 없이 빈 REF 목록으로 통과해야 한다
    refs = get_refs_for_panel(["SENTINEL_YIELD", "CRYPTO_SHADE"])
    assert refs == []


def test_unknown_non_guest_id_still_fatal() -> None:
    with pytest.raises(UnknownCharacterError):
        get_refs_for_panel(["TOTALLY_FAKE_ID"])
