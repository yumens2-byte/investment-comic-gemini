"""event_classifier 판정 축 테스트 (2026-09-03 개정: VIX OR화 + NASDAQ/BTC 축)."""

from engine.analysis.event_classifier import classify

_QUIET_ARC = {"yesterday_type": "INTEL", "tension": 10, "days_since_last": 3}


def _delta(**kw):
    base = {
        "WTI": {"curr": 83.9, "pct": 0.0},
        "VIX": {"curr": 14.5, "pct": 0.0},
        "DGS10": {"curr": 4.5, "pct": 0.0},
        "SPY": {"curr": -0.1, "pct": -0.1},
        "NASDAQ": {"curr": -0.3, "pct": -0.3},
        "BTC": {"curr": 78000.0, "pct": 0.5},
    }
    base.update(kw)
    return base


def test_quiet_market_stays_intel() -> None:
    assert classify(_delta(), _QUIET_ARC) == "INTEL"


def test_nasdaq_collapse_triggers_battle() -> None:
    # 2026-09-01 셀오프 유형: 기술주 주도 급락 (기존엔 판정 축 자체가 없었음)
    assert classify(_delta(NASDAQ={"curr": -2.5, "pct": -2.5}), _QUIET_ARC) == "BATTLE"


def test_vix_spike_pct_alone_triggers_shock() -> None:
    # 저변동 국면의 +25% 급등 (14 → 17.5): 구 AND 로직에선 레벨 28 미달로 무시됨
    assert classify(_delta(VIX={"curr": 17.5, "pct": 25.0}), _QUIET_ARC) == "SHOCK"


def test_vix_level_alone_triggers_shock() -> None:
    assert classify(_delta(VIX={"curr": 25.0, "pct": 1.0}), _QUIET_ARC) == "SHOCK"


def test_btc_crash_and_surge_trigger_battle() -> None:
    assert classify(_delta(BTC={"curr": 70000.0, "pct": -8.0}), _QUIET_ARC) == "BATTLE"
    assert classify(_delta(BTC={"curr": 85000.0, "pct": 8.0}), _QUIET_ARC) == "BATTLE"


def test_spy_collapse_still_battle() -> None:
    assert classify(_delta(SPY={"curr": -3.2, "pct": -3.2}), _QUIET_ARC) == "BATTLE"


def test_missing_new_axes_do_not_crash() -> None:
    # 과거 스냅샷 재처리 등 NASDAQ/BTC 키 부재 시 기존 경로 유지
    delta = _delta()
    delta.pop("NASDAQ")
    delta.pop("BTC")
    assert classify(delta, _QUIET_ARC) == "INTEL"


def test_snapshot_2026_09_02_with_default_thresholds() -> None:
    # 어제 실측 스냅샷: 기본 임계(dgs10 4.8)로는 여전히 INTEL —
    # 이 케이스의 메이저 승격은 Notion 임계 조정(dgs10 4.7)이 담당한다는 계약 고정
    delta = _delta(
        VIX={"curr": 14.92, "pct": 3.4},
        DGS10={"curr": 4.75, "pct": 1.7},
        SPY={"curr": -0.687, "pct": -0.687},
        NASDAQ={"curr": -1.0281, "pct": -1.0281},
        BTC={"curr": 77240.25, "pct": -2.29},
    )
    assert classify(delta, _QUIET_ARC) == "INTEL"
