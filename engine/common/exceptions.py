"""
engine/common/exceptions.py
ICG 파이프라인 전용 커스텀 예외 계층.
모든 도메인 예외는 이 모듈에서 정의한다.
"""


class ICGBaseError(Exception):
    """ICG 파이프라인 최상위 예외."""


# ── Canon 관련 ────────────────────────────────────────────────────────────────


class CanonLockViolation(ICGBaseError):
    """
    캐릭터 REF 이미지의 SHA256 해시가 characters.yaml 기록값과 불일치할 때 발생.
    파이프라인은 즉시 중단되어야 한다 (이미지 생성 전).
    """

    def __init__(self, char_id: str, expected: str, actual: str) -> None:
        self.char_id = char_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Canon Lock Violation: {char_id} — "
            f"expected sha256={expected[:12]}... got {actual[:12]}..."
        )


class UnknownCharacterError(ICGBaseError):
    """characters.yaml에 등록되지 않은 char_id 참조 시 발생."""

    def __init__(self, char_id: str) -> None:
        self.char_id = char_id
        super().__init__(f"Unknown character id: {char_id}")


# ── Battle / Narrative 관련 ───────────────────────────────────────────────────


class BattleOverride(ICGBaseError):
    """
    Claude가 battle_calc.py의 결정론적 결과와 다른 outcome을 생성했을 때 발생.
    Claude는 outcome 해석만 담당하며, 결과를 변경할 수 없다.
    """

    def __init__(self, expected_outcome: str, claude_outcome: str) -> None:
        self.expected_outcome = expected_outcome
        self.claude_outcome = claude_outcome
        super().__init__(
            f"Battle Override 감지: battle_calc={expected_outcome}, "
            f"Claude 생성={claude_outcome}. 파이프라인 중단."
        )


class NarrativeValidationError(ICGBaseError):
    """
    EpisodeScript Pydantic 검증 실패 시 발생.
    최대 2회 재시도 후에도 실패하면 파이프라인 중단.
    """

    def __init__(self, attempt: int, detail: str) -> None:
        self.attempt = attempt
        self.detail = detail
        super().__init__(f"Narrative 검증 실패 (시도 {attempt}/2): {detail}")


class InvalidVillainNameError(ICGBaseError):
    """
    Canon 빌런 6종 외 이름이 에피소드에 포함된 경우 발생.
    허용 목록: Oil Shock Titan, Debt Titan, Liquidity Leviathan,
               Volatility Hydra, Algorithm Reaper, War Dominion
    """

    def __init__(self, villain_name: str) -> None:
        self.villain_name = villain_name
        super().__init__(
            f"비캐넌 빌런명 감지: '{villain_name}'. "
            "허용 목록: Oil Shock Titan / Debt Titan / Liquidity Leviathan / "
            "Volatility Hydra / Algorithm Reaper / War Dominion"
        )


# ── Publish / Disclaimer 관련 ─────────────────────────────────────────────────


class DisclaimerMissing(ICGBaseError):
    """
    SNS 발행 콘텐츠에 투자 고지 문구가 누락된 경우 발생.
    x_publisher.py가 발행 직전 검증; ValueError 대신 이 예외를 사용한다.
    필수 문구: '본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다'
    """

    def __init__(self, location: str = "caption_x_final") -> None:
        self.location = location
        super().__init__(
            f"Disclaimer 미포함 감지 ({location}). "
            "발행 차단: '본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다' 필수."
        )


# ── Status State Machine 관련 ─────────────────────────────────────────────────


class InvalidStatusTransition(ICGBaseError):
    """
    episode_assets.status 전환이 허용된 state machine 경로를 벗어날 때 발생.
    허용 경로: draft > narrative_done > image_generated > dialog_pending >
               dialog_confirmed > assembled > published
    예외 상태: failed, aborted (어느 단계에서도 전환 가능)
    """

    ALLOWED_TRANSITIONS: dict[str, list[str]] = {
        "draft": ["narrative_done", "failed", "aborted"],
        "narrative_done": ["image_generated", "failed", "aborted"],
        "image_generated": ["dialog_pending", "failed", "aborted"],
        "dialog_pending": ["dialog_confirmed", "aborted"],
        "dialog_confirmed": ["assembled", "failed", "aborted"],
        "assembled": ["published", "failed", "aborted"],
        "published": [],
        "failed": ["draft"],  # 재시도 허용
        "aborted": [],
    }

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        allowed = self.ALLOWED_TRANSITIONS.get(current, [])
        super().__init__(f"Status 전환 불가: {current} → {target}. " f"허용 전환: {allowed}")


# ── Data / API 관련 ───────────────────────────────────────────────────────────


class DataFetchError(ICGBaseError):
    """외부 API(FRED, yfinance, LunarCrush, Crypto.com) 수집 실패 시 발생."""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        super().__init__(f"[{source}] 데이터 수집 실패: {detail}")


class PipelineAborted(ICGBaseError):
    """파이프라인 전체 중단이 필요한 치명적 오류 시 발생."""

    def __init__(self, step: str, reason: str) -> None:
        self.step = step
        super().__init__(f"파이프라인 중단 (step={step}): {reason}")
