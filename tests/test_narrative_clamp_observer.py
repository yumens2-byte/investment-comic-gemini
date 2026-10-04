"""
tests/test_narrative_clamp_observer.py
2026-10-05 장애(arc_tension_delta=12 → 스키마 le=10 위반으로 STEP_4 종료) 재발 방지 검증.

P1: _clamp_numeric_fields — 정수 필드 범위 보정
P2: attempt_observer — 내부 재시도 실패/보정 내역을 호출자 로그(run.log)로 전달
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import engine.narrative.claude_client as cc
from engine.common.exceptions import NarrativeValidationError
from engine.common.logger import StepLogger
from tests.test_schema import _make_valid_script


# ── P1: 범위 보정 단위 테스트 ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("given", "expected", "clamped"),
    [
        (12, 10, True),  # 2026-10-05 실제 장애 값
        (-15, -10, True),
        ("12", 10, True),  # 문자열 정수
        (" -3 ", -3, True),  # 문자열 정수 (범위 내) → int 변환됨
        (12.0, 10, True),  # 정수값 float
        (10, 10, False),  # 경계값 유지
        (-10, -10, False),
        (5, 5, False),
    ],
)
def test_clamp_numeric_fields_bounds(given, expected, clamped):
    raw = {"arc_tension_delta": given}
    notes = cc._clamp_numeric_fields(raw)
    assert raw["arc_tension_delta"] == expected
    assert bool(notes) is clamped


@pytest.mark.parametrize("given", [True, 12.5, "열둘", None, [12]])
def test_clamp_leaves_non_integer_values_to_schema(given):
    raw = {"arc_tension_delta": given}
    assert cc._clamp_numeric_fields(raw) == []
    assert raw["arc_tension_delta"] is given or raw["arc_tension_delta"] == given


def test_clamp_ignores_missing_field():
    raw = {"title": "x"}
    assert cc._clamp_numeric_fields(raw) == []
    assert "arc_tension_delta" not in raw


# ── generate_episode 통합 (Anthropic 호출은 fake) ────────────────────────────
def _fake_client(payloads: list[str], calls: list[dict]):
    def create(**kwargs):
        calls.append(kwargs)
        text = payloads[min(len(calls), len(payloads)) - 1]
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def _run(monkeypatch, payloads, observer=None):
    calls: list[dict] = []
    monkeypatch.setattr(cc, "Anthropic", lambda: _fake_client(payloads, calls))
    monkeypatch.setattr(cc, "load_system_prompt", lambda: "canon")
    monkeypatch.setattr(cc, "render_user_prompt", lambda **kwargs: "market evidence")
    script = cc.generate_episode(
        date="2026-04-14",
        episode_id="ICG-2026-04-14-001",
        event_type="BATTLE",
        delta={},
        battle_result={"outcome": "OBSERVATION"},
        hero_id="CHAR_HERO_003",
        villain_id="",
        arc_context={},
        scenario_type="NO_BATTLE",
        attempt_observer=observer,
    )
    return script, calls


def test_generate_episode_clamps_out_of_range_delta_without_retry(monkeypatch):
    events: list[tuple] = []
    payload = json.dumps(_make_valid_script(arc_tension_delta=12), ensure_ascii=False)
    script, calls = _run(monkeypatch, [payload], observer=lambda *e: events.append(e))

    assert script.arc_tension_delta == 10
    assert len(calls) == 1  # 재시도 비용 없이 1회에 통과
    assert events[0][0] == "warning"
    assert "[NarrativeClamp]" in events[0][1]
    assert events[0][2]["clamped"] == ["arc_tension_delta 12→10"]


def test_generate_episode_reports_every_failed_attempt(monkeypatch):
    events: list[tuple] = []
    with pytest.raises(NarrativeValidationError):
        _run(monkeypatch, ["not json"], observer=lambda *e: events.append(e))

    attempts = [e for e in events if "[NarrativeAttempt]" in e[1]]
    assert [e[2]["attempt"] for e in attempts] == [1, 2, 3]
    assert [e[2]["model"] for e in attempts] == [
        cc._MODEL_PRIMARY,
        cc._MODEL_PRIMARY,
        cc._MODEL_FALLBACK,
    ]
    assert all(e[2]["exception_type"] == "JSONDecodeError" for e in attempts)


def test_observer_failure_does_not_break_generation(monkeypatch):
    def broken(*_):
        raise RuntimeError("logger down")

    payload = json.dumps(_make_valid_script(arc_tension_delta=-99), ensure_ascii=False)
    script, _ = _run(monkeypatch, [payload], observer=broken)
    assert script.arc_tension_delta == -10


def test_generate_episode_without_observer_is_backward_compatible(monkeypatch):
    payload = json.dumps(_make_valid_script(arc_tension_delta=3), ensure_ascii=False)
    script, _ = _run(monkeypatch, [payload])
    assert script.arc_tension_delta == 3


# ── P2: 실제 StepLogger → run.log(JSONL) 기록 확인 ──────────────────────────
def test_attempt_failures_are_written_to_run_log(monkeypatch, tmp_path):
    step_logger = StepLogger(
        run_id="ICG-TEST",
        episode_date="2026-04-14",
        output_dir=tmp_path,
        supabase_enabled=False,
    )

    def observer(level, message, meta):
        log_fn = step_logger.warning if level == "warning" else step_logger.info
        log_fn("STEP_4", message, meta=meta)

    bad = json.dumps(_make_valid_script(caption_x_final="면책 없음"), ensure_ascii=False)
    good = json.dumps(_make_valid_script(arc_tension_delta=12), ensure_ascii=False)
    script, _ = _run(monkeypatch, [bad, good], observer=observer)
    assert script.arc_tension_delta == 10

    records = [json.loads(line) for line in (tmp_path / "run.log").read_text("utf-8").splitlines()]
    messages = [r["message"] for r in records]
    assert any("[NarrativeAttempt] 시도 1/3 실패" in m for m in messages)
    assert any("[NarrativeClamp] 시도 2/3" in m for m in messages)
    assert all(r["step"] == "STEP_4" and r["level"] == "warning" for r in records)
