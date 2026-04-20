"""Storyline diversity guard.

목표:
- 시장 데이터 기반 기본 시나리오를 존중하되,
- 최근 에피소드에서 동일 시나리오가 연속 반복될 때
  과도한 스토리라인 중복을 완화한다.
"""

from __future__ import annotations

from collections.abc import Sequence

ScenarioType = str


def _tail_streak(values: Sequence[str], target: str) -> int:
    """values의 끝에서 target이 연속된 길이 반환."""
    streak = 0
    for v in reversed(values):
        if v == target:
            streak += 1
        else:
            break
    return streak


def _allowed_scenarios(risk_level: str, event_type: str) -> list[ScenarioType]:
    """현재 시장 컨텍스트에서 허용 가능한 시나리오 후보를 반환."""
    rl = (risk_level or "MEDIUM").upper()
    et = (event_type or "NORMAL").upper()

    # crisis 구간: ALLIANCE 허용
    if rl == "HIGH" and et in {"BATTLE", "SHOCK"}:
        return ["ALLIANCE", "ONE_VS_ONE"]

    # calm 구간: NO_BATTLE 허용
    if rl == "LOW" and et in {"NORMAL", "INTEL"}:
        return ["NO_BATTLE", "ONE_VS_ONE"]

    # 나머지 구간: ONE_VS_ONE 중심
    return ["ONE_VS_ONE"]


def choose_scenario_with_diversity(
    base_scenario: ScenarioType,
    risk_level: str,
    event_type: str,
    recent_scenarios: Sequence[str],
    *,
    max_same_streak: int = 2,
) -> tuple[ScenarioType, str]:
    """
    기본 시나리오를 입력받아 중복 완화 보정 시나리오를 반환.

    규칙:
    - 최근 tail streak가 max_same_streak 미만이면 그대로 유지.
    - streak 초과 시 현재 시장 구간에서 허용되는 후보 중
      base와 다른 첫 후보로 회전.
    - 허용 후보가 base 뿐이면 그대로 유지.

    Returns:
        (scenario, reason)
    """
    base = (base_scenario or "ONE_VS_ONE").upper()
    recent = [str(s).upper() for s in recent_scenarios if s]
    streak = _tail_streak(recent, base)

    if streak < max_same_streak:
        return base, f"keep_base(streak={streak})"

    candidates = _allowed_scenarios(risk_level, event_type)
    for candidate in candidates:
        if candidate != base:
            return candidate, (
                "rotated_for_diversity"
                f"(base={base},streak={streak},risk={risk_level},event={event_type})"
            )

    return base, f"no_alternative_allowed(base={base},streak={streak})"
