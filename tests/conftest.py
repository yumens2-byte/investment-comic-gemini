"""
tests/conftest.py
ICG character 엔진 전용 mock — engine.common.supabase_client만 모킹
engine.common.notion_loader 등 무거운 의존 없음
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ── engine.common.supabase_client mock ───────────────────
_mock_table = MagicMock()
_mock_table.select.return_value = _mock_table
_mock_table.update.return_value = _mock_table
_mock_table.eq.return_value = _mock_table
_mock_table.limit.return_value = _mock_table
_mock_table.execute.return_value = MagicMock(data=[])

_mock_sb_module = MagicMock()
_mock_sb_module.icg_table = lambda table_name: _mock_table
sys.modules["engine.common.supabase_client"] = _mock_sb_module
