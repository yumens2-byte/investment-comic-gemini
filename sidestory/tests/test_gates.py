from __future__ import annotations

from sidestory.core import gates
from sidestory.core.canon_rules import DISCLAIMER
from sidestory.core.echo import build_echo_pack
from sidestory.tests.fixtures import arc_row, main_row, market_row


def _echo():
    return build_echo_pack("2026-10-06", main_row(), market_row(), arc_row())


def test_sg0_skip_paths() -> None:
    assert gates.sg0_anchor(None, True, False).skip
    assert gates.sg0_anchor(main_row(), False, False).skip
    assert gates.sg0_anchor(main_row(), False, True).passed


def test_sg1_sg7() -> None:
    assert not gates.sg1_record(None).passed
    assert gates.sg1_record("b" * 64).passed
    assert gates.sg7_unchanged("a" * 64, "a" * 64).passed
    assert not gates.sg7_unchanged("a" * 64, "c" * 64).passed


def test_sg3_blocks_node_names_and_faction_declaration_at_e01() -> None:
    bad = {"panels": [{"narration": "Null Trader가 나타났다"},
                      {"key_text": "우리는 New Network다"}]}
    result = gates.sg3_stage(bad, "E01")
    assert not result.passed
    assert "node name" in result.reason and "faction" in result.reason
    assert gates.sg3_stage({"panels": [{"narration": "멀리 그림자가 스친다"}]}, "E01").passed


def test_sg4_echo_contract() -> None:
    echo = _echo()
    ok = {"title": "관찰 일지", "panels": [
        {"narration": f"{echo.title} — 그날 10년물은 5.24였다"}]}
    assert gates.sg4_echo_contract(ok, echo).passed
    not_cited = {"panels": [{"narration": "아무 일도 없었다"}]}
    assert "EC-1" in gates.sg4_echo_contract(not_cited, echo).reason
    wrong_number = {"panels": [{"narration": f"{echo.title} 10년물 5.99"}]}
    assert "EC-2" in gates.sg4_echo_contract(wrong_number, echo).reason
    resolved = {"panels": [{"narration": f"{echo.title}. 첨탑의 균열은 어디서 시작됐나 — 해결됐다"}]}
    assert "EC-3" in gates.sg4_echo_contract(resolved, echo).reason


def test_sg5_disclaimer_and_vendor() -> None:
    assert gates.sg5_copy(f"끝. {DISCLAIMER}", ["본문"]).passed
    result = gates.sg5_copy("끝.", ["FRED 기준 금리"])
    assert "disclaimer missing" in result.reason and "FRED" in result.reason


def test_sg6_manifest() -> None:
    assert gates.sg6_manifest({"S1": "x"}, {"S1": "x"}).passed
    assert not gates.sg6_manifest({"S1": "x"}, {"S1": "y"}).passed
    assert not gates.sg6_manifest({}, {}).passed
