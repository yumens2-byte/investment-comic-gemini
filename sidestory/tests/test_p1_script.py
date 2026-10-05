"""SideScript normalisation/validation, beats, data card, image prompt, SG-2."""
from __future__ import annotations

import pytest

from sidestory.core import gates
from sidestory.core.beats import beats_for
from sidestory.core.canon_rules import DISCLAIMER
from sidestory.core.image_prompt import build_panel_spec, registered_refs
from sidestory.core.models import OutcomeClass
from sidestory.core.script import SidePanel, data_card, normalize, validate
from sidestory.tests.p1_fixtures import echo_for, make_refs, raw_script

SID = "SIDE-2026-10-06-01"


def _check(raw, echo=None, stage="E01"):
    echo = echo or echo_for()
    return validate(normalize(raw, side_episode_id=SID, echo=echo), echo, stage)


def test_valid_script_passes_and_has_eight_panels() -> None:
    parsed, problems = _check(raw_script())
    assert problems == []
    assert [p.idx for p in parsed.panels] == list(range(1, 9))
    assert parsed.panels[6].panel_type == "TEXT_CARD"
    assert parsed.panels[7].panel_type == "DISCLAIMER"
    assert parsed.panels[7].narration == DISCLAIMER
    assert parsed.caption_fb.endswith(DISCLAIMER)


def test_llm_panels_7_8_are_replaced_by_deterministic_ones() -> None:
    raw = raw_script()
    raw["panels"] += [{"idx": 7, "panel_type": "TEXT_CARD", "narration": "VIX 99.99"},
                      {"idx": 8, "panel_type": "DISCLAIMER", "narration": "아무 말"}]
    parsed, problems = _check(raw)
    assert problems == []
    assert "99.99" not in parsed.panels[6].narration


def test_data_card_numbers_only_from_echo() -> None:
    echo = echo_for()
    card = data_card(echo)
    assert len(card["narration"]) <= 120
    assert "VIX 15.31" in card["narration"] and "미 10년물 5.24%" in card["narration"]
    assert gates.sg4_echo_contract({"panels": [card], "title": echo.title}, echo).passed


def test_data_card_includes_dollar_label_when_present() -> None:
    from datetime import date

    from sidestory.core.dollar import DollarCandidate, DollarIndexKind, select_dollar
    from sidestory.core.echo import build_echo_pack
    from sidestory.tests.fixtures import arc_row, main_row, market_row

    dxy = DollarCandidate(kind=DollarIndexKind.DXY, value=101.93, as_of="2026-10-02",
                          source="t")
    decision = select_dollar(date(2026, 10, 5), dxy, None)
    echo = build_echo_pack("2026-10-06", main_row("2026-10-05"), market_row("2026-10-05"),
                           arc_row(), decision)
    card = data_card(echo)
    assert "달러인덱스 101.93(10-02)" in card["narration"]
    assert len(card["narration"]) <= 120
    assert gates.sg4_echo_contract({"panels": [card], "title": echo.title}, echo).passed


def test_data_card_drops_low_priority_items_first() -> None:
    echo = echo_for()
    echo.dollar = {"value": 101.93, "label_ko": "달러인덱스", "as_of": "2026-10-02"}
    echo.market = {**echo.market, "hy_spread": 3.24}
    from sidestory.core import script as mod

    old = mod.CARD_MAX
    mod.CARD_MAX = 80
    try:
        card = data_card(echo)
    finally:
        mod.CARD_MAX = old
    assert len(card["narration"]) <= 80
    assert "하이일드" not in card["narration"] and "미 10년물" in card["narration"]


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.update(title="x" * 41), "schema: title"),
    (lambda r: r["panels"].pop(), "panels must be idx"),
    (lambda r: r["panels"][1].update(narration="방패는 버텼다"), "must cite main"),
    (lambda r: r["panels"][3].update(zero_block_pose="attack"), "P4 pose attack"),
    (lambda r: r["panels"][4].update(silhouettes=["node_a", "node_b"]), "P5 silhouettes 2 > 1"),
    (lambda r: r["panels"][0].update(silhouettes=["node_a"]), "P1 silhouettes 1 > 0"),
    (lambda r: r["panels"][2].update(narration="VIX 17.80"), "EC-2 number not in echo: 17.80"),
    (lambda r: r["panels"][2].update(market_ref="VIX 17.80"), "EC-2 number not in echo: 17.80"),
    (lambda r: r["panels"][5].update(narration="Null Trader가 웃는다"), "node name before E05"),
    (lambda r: r["panels"][5].update(key_text="우리는 New Network다"), "faction declaration"),
    (lambda r: r.update(caption_fb="FRED 기준 금리"), "vendor term: FRED"),
    (lambda r: r["panels"][2].update(action="CHAR_HERO_001 raises a shield"),
     "main characters must not be drawn"),
    (lambda r: r["panels"][2].update(setting=""), "setting/action required"),
    (lambda r: r["panels"][2].update(panel_type="CLIMAX"), "P3 panel_type must be TENSION"),
    (lambda r: r["panels"][4].update(action="Phantom Relay walks"), "P5 node name"),
    (lambda r: r["panels"][4].update(silhouettes=["node_x"]), "schema: panels.4.silhouettes"),
])
def test_validation_rejects(mutate, needle) -> None:
    raw = raw_script()
    mutate(raw)
    _, problems = _check(raw)
    assert any(needle in p for p in problems), problems


def test_defeat_requires_defense_pose_and_allows_two_silhouettes() -> None:
    echo = echo_for("HERO_DEFEAT")
    _, problems = _check(raw_script(pose4="side"), echo)
    assert any("P4 pose side" in p for p in problems)
    _, problems = _check(raw_script(pose4="defense", silhouettes5=["node_a", "node_c"]), echo)
    assert problems == []


def test_no_battle_class_beats() -> None:
    echo = echo_for("OBSERVATION", "NO_BATTLE")
    assert echo.outcome_class is OutcomeClass.NO_BATTLE
    _, problems = _check(raw_script(), echo)
    assert problems == []


@pytest.mark.parametrize("cls", list(OutcomeClass))
def test_beats_shape(cls) -> None:
    beats = beats_for(cls)
    assert [b.idx for b in beats] == [1, 2, 3, 4, 5, 6]
    assert sum(b.max_silhouettes for b in beats) == (2 if cls is OutcomeClass.DEFEAT else 1)
    assert [b.idx for b in beats if b.must_cite_main] == [2]
    assert "attack" not in beats[3].allowed_poses


def test_caption_overflow_with_disclaimer_rejected() -> None:
    raw = raw_script()
    raw["caption_fb"] = "가" * 1490
    _, problems = _check(raw)
    assert any("caption_fb" in p for p in problems)


def test_image_prompt_ref_and_negative(tmp_path) -> None:
    chars = make_refs(tmp_path)
    panel = SidePanel(idx=4, panel_type="CLIMAX", setting="rooftop", action="observes",
                      zero_block_pose="side", silhouettes=["node_c"])
    spec = build_panel_spec(panel, chars)
    assert spec.ref_path == "sidestory/assets/refs/zero_block_side.png"
    assert "IDENTITY LOCK" in spec.prompt and "NEGATIVE" in spec.prompt
    assert "cube-fortress" in spec.prompt and "no text" in spec.prompt
    none = build_panel_spec(SidePanel(idx=1, panel_type="COVER", setting="s", action="a"), chars)
    assert none.ref_path is None and "environment only" in none.prompt
    assert build_panel_spec(panel, chars).prompt == spec.prompt  # deterministic (ledger reuse)


def test_registered_refs_and_sg2(tmp_path) -> None:
    chars = make_refs(tmp_path)
    refs = registered_refs(chars, {"side", "none"})
    assert [r[0] for r in refs] == ["side"]
    pose, path, sha = refs[0]
    assert gates.sg2_refs([(pose, sha, sha)]).passed
    assert "mismatch" in gates.sg2_refs([(pose, sha, "0" * 64)]).reason
    assert "missing" in gates.sg2_refs([(pose, sha, None)]).reason
    assert "not registered" in gates.sg2_refs([(pose, "__PENDING__", sha)]).reason
    assert gates.sg2_refs([]).passed  # environment-only scripts need no REF


def test_repo_refs_registered_and_match_committed_files() -> None:
    """SG-2 against the real repo: every Zero Block REF is committed and its sha256 registered."""
    import hashlib

    from sidestory.app.settings import load_characters
    from sidestory.tests.conftest import REPO_ROOT

    refs = registered_refs(load_characters(), {"front", "side", "back", "attack", "defense"})
    assert len(refs) == 5
    checks = []
    for pose, path, sha in refs:
        file = REPO_ROOT / path
        checks.append((pose, sha, hashlib.sha256(file.read_bytes()).hexdigest()
                       if file.is_file() else None))
    result = gates.sg2_refs(checks)
    assert result.passed, result.reason
