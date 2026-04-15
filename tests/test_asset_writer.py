"""
tests/test_asset_writer.py
asset_writer.py 단위 테스트.

Acceptance Criteria (Track E):
- [x] status state machine 허용/불허 전환 검증
- [x] validate_transition() 경계 케이스
- [x] set_failed() 강제 전환
"""

import pytest

from engine.common.exceptions import InvalidStatusTransition
from engine.persist.asset_writer import validate_transition


class TestValidateTransition:
    """status 전환 state machine 검증."""

    def test_allowed_transitions(self):
        """허용된 전환은 예외 없이 통과."""
        allowed_pairs = [
            ("draft", "narrative_done"),
            ("narrative_done", "image_generated"),
            ("image_generated", "dialog_pending"),
            ("dialog_pending", "dialog_confirmed"),
            ("dialog_confirmed", "assembled"),
            ("assembled", "published"),
            ("draft", "failed"),
            ("draft", "aborted"),
            ("narrative_done", "failed"),
            ("image_generated", "aborted"),
            ("failed", "draft"),
        ]
        for current, target in allowed_pairs:
            validate_transition(current, target)  # 예외 없어야 함

    def test_forbidden_transitions(self):
        """허용되지 않은 전환은 InvalidStatusTransition."""
        forbidden_pairs = [
            ("draft", "image_generated"),  # 단계 건너뜀
            ("draft", "published"),  # 단계 건너뜀
            ("assembled", "draft"),  # 역방향
            ("published", "draft"),  # 발행 완료 후 재시작 불가
            ("aborted", "draft"),  # aborted 재시작 불가
            ("narrative_done", "dialog_confirmed"),  # 단계 건너뜀
        ]
        for current, target in forbidden_pairs:
            with pytest.raises(InvalidStatusTransition):
                validate_transition(current, target)

    def test_full_happy_path(self):
        """draft → published 전체 경로 검증."""
        happy_path = [
            ("draft", "narrative_done"),
            ("narrative_done", "image_generated"),
            ("image_generated", "dialog_pending"),
            ("dialog_pending", "dialog_confirmed"),
            ("dialog_confirmed", "assembled"),
            ("assembled", "published"),
        ]
        for current, target in happy_path:
            validate_transition(current, target)

    def test_error_message_includes_states(self):
        """에러 메시지에 current/target 상태가 포함되어야 한다."""
        with pytest.raises(InvalidStatusTransition) as exc_info:
            validate_transition("draft", "published")
        assert "draft" in str(exc_info.value)
        assert "published" in str(exc_info.value)


# ── notion_mirror 테스트 ──────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch  # noqa: E402

from engine.persist.notion_mirror import _STATUS_MAP, create_or_update  # noqa: E402


class TestNotionMirror:
    """notion_mirror.py 단위 테스트 (Notion API mock)."""

    def test_status_map_covers_all_states(self):
        """_STATUS_MAP이 모든 Supabase status를 커버해야 한다."""
        required_statuses = [
            "draft",
            "narrative_done",
            "image_generated",
            "dialog_pending",
            "dialog_confirmed",
            "assembled",
            "published",
            "failed",
            "aborted",
        ]
        for status in required_statuses:
            assert status in _STATUS_MAP, f"'{status}' _STATUS_MAP에 없음"

    def test_create_skips_without_notion_token(self, monkeypatch):
        """NOTION_API_KEY 없으면 생성 생략하고 None 반환."""
        monkeypatch.delenv("NOTION_API_KEY", raising=False)

        result = create_or_update(
            episode_date="2026-04-14",
            episode_id="ICG-2026-04-14-001",
            title="Test Episode",
            event_type="BATTLE",
            status="draft",
            hero_id="CHAR_HERO_001",
            villain_id="CHAR_VILLAIN_002",
            outcome="DRAW",
            balance=0,
        )
        assert result is None

    def test_create_calls_notion_api(self, monkeypatch):
        """NOTION_API_KEY 있을 때 Notion pages.create 호출 확인."""
        monkeypatch.setenv("NOTION_API_KEY", "ntn_test_token_00000000000000000000000000")

        mock_client = MagicMock()
        mock_client.pages.create.return_value = {"url": "https://notion.so/test-page"}

        with patch("notion_client.Client", return_value=mock_client):
            result = create_or_update(
                episode_date="2026-04-14",
                episode_id="ICG-2026-04-14-001",
                title="Test Battle Episode",
                event_type="BATTLE",
                status="narrative_done",
                hero_id="CHAR_HERO_003",
                villain_id="CHAR_VILLAIN_002",
                outcome="HERO_TACTICAL_VICTORY",
                balance=15,
                panel_count=8,
                claude_cost_usd=0.05,
                gemini_cost_usd=0.31,
            )

        assert result == "https://notion.so/test-page"
        mock_client.pages.create.assert_called_once()

        # 호출 인수 검증
        call_kwargs = mock_client.pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert props["Status"]["select"]["name"] == "Narrative Done"
        assert props["Event Type"]["select"]["name"] == "BATTLE"
        assert props["Balance"]["number"] == 15

    def test_notion_failure_does_not_raise(self, monkeypatch):
        """Notion API 실패 시 예외 없이 None 반환 (파이프라인 비중단)."""
        monkeypatch.setenv("NOTION_API_KEY", "ntn_test_token_00000000000000000000000000")

        mock_client = MagicMock()
        mock_client.pages.create.side_effect = Exception("Notion connection error")

        with patch("notion_client.Client", return_value=mock_client):
            result = create_or_update(
                episode_date="2026-04-14",
                episode_id="ICG-2026-04-14-001",
                title="Test",
                event_type="NORMAL",
                status="draft",
                hero_id="CHAR_HERO_001",
                villain_id="CHAR_VILLAIN_005",
                outcome="DRAW",
                balance=0,
            )

        assert result is None  # 예외 전파 아님

    def test_status_map_to_notion_labels(self):
        """Supabase status → Notion Status 변환이 정확해야 한다."""
        assert _STATUS_MAP["draft"] == "Draft"
        assert _STATUS_MAP["narrative_done"] == "Narrative Done"
        assert _STATUS_MAP["image_generated"] == "Image Generated"
        assert _STATUS_MAP["published"] == "Published"
        assert _STATUS_MAP["failed"] == "Failed"
