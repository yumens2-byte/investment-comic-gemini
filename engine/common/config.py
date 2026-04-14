"""
engine/common/config.py
ICG 환경변수 로더.

원칙:
- 모든 secret은 환경변수 경유. 하드코딩 절대 금지.
- GEMINI_API_SUB_PAY_KEY 가 Gemini API key 이름이다 (GEMINI_API_KEY 사용 금지 — doc 19 patch).
- 로컬 실행 시 .env 파일 자동 로드.
- 필수 변수 누락 시 명확한 에러 메시지 출력 후 RuntimeError 발생.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# .env 파일이 존재하면 로드 (GitHub Actions에서는 .env 없으므로 무시)
_dotenv_path = Path(__file__).parents[2] / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path)


@dataclass(frozen=True)
class ICGConfig:
    """ICG 파이프라인 전역 설정. 불변(frozen) 데이터클래스."""

    # ── Anthropic ──────────────────────────────────────────
    anthropic_api_key: str

    # ── Gemini — GEMINI_API_SUB_PAY_KEY 고정 ────────────────────────────────
    # ⚠️  GEMINI_API_KEY 라는 이름은 코드 어디에도 사용하지 않는다.
    #    env var 이름: GEMINI_API_SUB_PAY_KEY (GitHub Secrets 기등록)
    pay_key: str

    # ── Supabase ─────────────────────────────────────────────
    supabase_url: str
    supabase_service_role_key: str
    supabase_schema: str = "icg"

    # ── Notion ───────────────────────────────────────────────
    notion_token: str = ""
    notion_tracker_ds: str = "485ba577-0512-45fd-9445-b9e86c53d88b"

    # ── 시장 데이터 ───────────────────────────────────────────
    fred_api_key: str = ""
    lunar_crush_api_key: str = ""  # optional

    # ── X (Twitter) ─────────────────────────────────────────
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""

    # ── Telegram ─────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_free_channel_id: str = ""
    telegram_paid_channel_id: str = ""

    # ── 운영 제어 ─────────────────────────────────────────────
    dry_run: bool = True
    force_run: bool = False


# 필수 환경변수 목록 — 없으면 파이프라인 기동 불가
_REQUIRED_VARS: list[str] = [
    "ANTHROPIC_API_KEY",
    "GEMINI_API_SUB_PAY_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
]


def load_config() -> ICGConfig:
    """
    환경변수를 읽어 ICGConfig 인스턴스를 반환한다.

    필수 변수 누락 시 RuntimeError를 발생시켜 파이프라인을 즉시 중단한다.
    secrets 값 자체는 이 함수에서 로그에 출력하지 않는다.
    """
    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"필수 환경변수 누락: {missing}. "
            "GitHub Secrets 또는 .env 파일을 확인하라."
        )

    def _bool(key: str, default: bool = False) -> bool:
        val = os.environ.get(key, str(default)).lower()
        return val in ("true", "1", "yes")

    return ICGConfig(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        pay_key=os.environ["GEMINI_API_SUB_PAY_KEY"],
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_service_role_key=os.environ["SUPABASE_KEY"],
        supabase_schema=os.environ.get("SUPABASE_SCHEMA", "icg"),
        notion_token=os.environ.get("NOTION_API_KEY", ""),
        notion_tracker_ds=os.environ.get(
            "NOTION_TRACKER_DS", "485ba577-0512-45fd-9445-b9e86c53d88b"
        ),
        fred_api_key=os.environ.get("FRED_API_KEY", ""),
        lunar_crush_api_key=os.environ.get("LUNAR_CRUSH_API_KEY", ""),
        x_api_key=os.environ.get("X_API_KEY", ""),
        x_api_secret=os.environ.get("X_API_SECRET", ""),
        x_access_token=os.environ.get("X_ACCESS_TOKEN", ""),
        x_access_secret=os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_free_channel_id=os.environ.get("TELEGRAM_FREE_CHANNEL_ID", ""),
        telegram_paid_channel_id=os.environ.get("TELEGRAM_PAID_CHANNEL_ID", ""),
        dry_run=_bool("DRY_RUN", default=True),
        force_run=_bool("FORCE_RUN", default=False),
    )


# 모듈 수준 싱글톤 — 최초 import 시 한 번만 로드
# 테스트에서 os.environ 패치 후 reload_config()로 재초기화
_config: ICGConfig | None = None


def get_config() -> ICGConfig:
    """ICGConfig 싱글톤 반환. 최초 호출 시 환경변수 로드."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> ICGConfig:
    """테스트용: 환경변수 변경 후 강제 재로드."""
    global _config
    _config = load_config()
    return _config
