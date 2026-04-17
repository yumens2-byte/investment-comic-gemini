"""
tests/conftest.py
전수 테스트용 공통 픽스처 — 외부 API mock (Supabase, Notion, Anthropic).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# ── Supabase client mock ───────────────────────────────────────────────────────
_mock_table = MagicMock()
_mock_table.select.return_value = _mock_table
_mock_table.upsert.return_value = _mock_table
_mock_table.update.return_value = _mock_table
_mock_table.insert.return_value = _mock_table
_mock_table.eq.return_value = _mock_table
_mock_table.order.return_value = _mock_table
_mock_table.limit.return_value = _mock_table
_mock_table.execute.return_value = MagicMock(data=[])

mock_sb_module = MagicMock()
mock_sb_module.icg_table = lambda table_name: _mock_table
sys.modules["engine.common.supabase_client"] = mock_sb_module

# ── notion_client mock (test_asset_writer 용) ──────────────────────────────────
mock_notion_client_module = MagicMock()
sys.modules["notion_client"] = mock_notion_client_module

# ── requests mock (notion_loader 외부 API 호출 차단) ──────────────────────────
os.environ.setdefault("NOTION_API_KEY", "ntn_test_token_00000000000000000000000000")

mock_requests = MagicMock()
mock_requests.get.return_value = MagicMock(
    status_code=200,
    json=lambda: {"results": []},
)
sys.modules["requests"] = mock_requests

# ── notion_loader: 실제 함수 유지, 외부 API 함수만 mock 교체 ─────────────────
import engine.common.notion_loader as _real_notion_loader  # noqa: E402

_MOCK_TEMPLATE = """## Battle Scenario: {{ scenario_type }}
{% if scenario_type == 'NO_BATTLE' %}
Hero: {{ hero_id }}
Villain: NONE
{% elif scenario_type == 'ALLIANCE' %}
Hero 1: {{ hero_ids[0] }}
Hero 2: {{ hero_ids[1] }}
Villain: {{ villain_id }}
{% else %}
Hero: {{ hero_id }}
Villain: {{ villain_id }}
Outcome: {{ battle_result.outcome }}
{% endif %}
Ending Tone: {{ ending_tone }}
"""

_real_notion_loader.load_narrative_user_template = lambda: _MOCK_TEMPLATE
_real_notion_loader.load_narrative_system = lambda: "You are an ICG episode generator."
_real_notion_loader.load_characters_canon = lambda: {
    "heroes": {
        "CHAR_HERO_001": {"name_ko": "EDT", "name_en": "EDT", "base_power": 75},
        "CHAR_HERO_002": {"name_ko": "아이언 누나", "name_en": "Iron Nuna", "base_power": 73},
        "CHAR_HERO_003": {"name_ko": "익스포저 걸", "name_en": "Exposure Girl", "base_power": 74},
        "CHAR_HERO_004": {"name_ko": "골드본드", "name_en": "Gold Bond", "base_power": 72},
        "CHAR_HERO_005": {"name_ko": "히어로5", "name_en": "Hero5", "base_power": 71},
    },
    "villains": {
        "CHAR_VILLAIN_001": {"name_ko": "데트 타이탄", "name_en": "Debt Titan", "base_power": 72, "event": "BATTLE"},
        "CHAR_VILLAIN_002": {"name_ko": "오일쇼크 타이탄", "name_en": "Oil Shock Titan", "base_power": 74, "event": "BATTLE"},
        "CHAR_VILLAIN_003": {"name_ko": "리퀴디티", "name_en": "Liquidity Leviathan", "base_power": 70, "event": "AFTERMATH"},
        "CHAR_VILLAIN_004": {"name_ko": "볼라틸리티 히드라", "name_en": "Volatility Hydra", "base_power": 75, "event": "SHOCK"},
        "CHAR_VILLAIN_005": {"name_ko": "알고리즘 리퍼", "name_en": "Algorithm Reaper", "base_power": 71, "event": "NORMAL"},
        "CHAR_VILLAIN_006": {"name_ko": "워 도미니언", "name_en": "War Dominion", "base_power": 73, "event": "BATTLE"},
    },
}
_real_notion_loader.load_battle_constants = lambda: {
    "CHARACTER_BASE_POWER": {
        "CHAR_HERO_001": 75, "CHAR_HERO_002": 73, "CHAR_HERO_003": 74,
        "CHAR_HERO_004": 72, "CHAR_HERO_005": 71,
        "CHAR_VILLAIN_001": 72, "CHAR_VILLAIN_002": 74, "CHAR_VILLAIN_003": 70,
        "CHAR_VILLAIN_004": 75, "CHAR_VILLAIN_005": 71, "CHAR_VILLAIN_006": 73,
    },
    "OUTCOME_THRESHOLDS": {
        "HERO_VICTORY": 30, "HERO_TACTICAL_VICTORY": 10,
        "DRAW_LOWER": -5, "VILLAIN_TEMP_VICTORY": -10, "HERO_DEFEAT": -30,
    },
    "HERO_BONUS_TABLE": {},
}
# char_design_to_prompt_block, get_char_designs 는 실제 함수 그대로 유지
