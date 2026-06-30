"""step_analysis 추출 헬퍼 단위 테스트 (A-리팩토링 2026-06-30).

step_analysis 680줄에서 분리한 헬퍼가 독립적으로 단위 테스트 가능함을 보인다.
외부 의존이 없는 순수 헬퍼 위주로 동작을 고정한다(회귀 방지).
"""

from __future__ import annotations

from scripts.run_market import _build_sector_rank, _resolve_base_power


def test_build_sector_rank_none_signal_pack() -> None:
    assert _build_sector_rank(None) == (None, None, None)


def test_build_sector_rank_empty_sector() -> None:
    assert _build_sector_rank({"by_domain": {"sector": []}}) == (None, None, None)


def test_build_sector_rank_sorted_desc_and_areas() -> None:
    signal_pack = {
        "by_domain": {
            "sector": [
                {"symbol": "XLK", "name": "Tech", "change_pct": 2.0},
                {"symbol": "XLE", "name": "Energy", "change_pct": -1.0},
                {"symbol": "XLF", "name": "Fin", "change_pct": 0.5},
            ]
        }
    }
    rank, watch, caution = _build_sector_rank(signal_pack)
    # change_pct 내림차순 정렬
    assert [r["symbol"] for r in rank] == ["XLK", "XLF", "XLE"]
    # watch = 상위 3개 이름
    assert watch == ["Tech", "Fin", "Energy"]
    # caution = 하위 3개를 역순 → [Energy, Fin, Tech]
    assert caution == ["Energy", "Fin", "Tech"]


def test_build_sector_rank_ignores_none_change_pct() -> None:
    signal_pack = {
        "by_domain": {
            "sector": [
                {"symbol": "XLK", "name": "Tech", "change_pct": None},
                {"symbol": "XLF", "name": "Fin", "change_pct": 1.0},
            ]
        }
    }
    rank, _watch, _caution = _build_sector_rank(signal_pack)
    assert [r["symbol"] for r in rank] == ["XLF"]


def test_resolve_base_power_uses_canon_when_constants_empty(monkeypatch) -> None:
    import engine.common.notion_loader as nl

    monkeypatch.setattr(nl, "load_battle_constants", lambda: {})
    canon = {"heroes": {"H": {"base_power": 80}}, "villains": {"V": {"base_power": 70}}}
    assert _resolve_base_power(canon, "H", "V") == (80, 70)


def test_resolve_base_power_defaults_when_missing(monkeypatch) -> None:
    import engine.common.notion_loader as nl

    monkeypatch.setattr(nl, "load_battle_constants", lambda: {})
    canon = {"heroes": {}, "villains": {}}
    assert _resolve_base_power(canon, "X", "Y") == (75, 72)


def test_resolve_base_power_prefers_battle_constants(monkeypatch) -> None:
    import engine.common.notion_loader as nl

    monkeypatch.setattr(
        nl,
        "load_battle_constants",
        lambda: {"CHARACTER_BASE_POWER": {"H": 99, "V": 88}},
    )
    canon = {"heroes": {"H": {"base_power": 80}}, "villains": {"V": {"base_power": 70}}}
    assert _resolve_base_power(canon, "H", "V") == (99, 88)
