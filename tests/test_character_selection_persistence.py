from engine.persist.asset_writer import (
    _update_daily_analysis_schema_compatible,
    character_selection_candidate_rows,
    character_selection_summary,
)
from scripts.run_market import _build_episode_asset_payload


def _ctx() -> dict:
    return {
        "event_type": "BATTLE",
        "scenario_type": "ONE_VS_ONE",
        "risk_level": "MEDIUM",
        "hero_id": "CHAR_HERO_003",
        "battle_result": {"outcome": "DRAW", "balance": 0},
        "heroes": ["CHAR_HERO_003"],
        "active_character_cards": [{"char_id": "CHAR_HERO_003"}],
        "character_selection": {
            "version": "character-appearance-v2",
            "scenario_type": "ONE_VS_ONE",
            "event_type": "BATTLE",
            "risk_level": "MEDIUM",
            "primary_hero": "CHAR_HERO_003",
            "support_heroes": [],
            "heroes": ["CHAR_HERO_003"],
            "primary_villain": "CHAR_VILLAIN_002",
            "neutral_guests": [{"char_id": "SENTINEL_YIELD", "role": "WARNER"}],
            "selection_reason": "ONE_VS_ONE selected by score",
            "all_candidates": [
                {
                    "char_id": "CHAR_HERO_003",
                    "faction": "HERO",
                    "role": "PRIMARY_HERO",
                    "appear": True,
                    "score": 105,
                    "threshold": 60,
                    "rank": 1,
                    "reasons": ["WTI pct >= 8 calls Leverage"],
                    "score_breakdown": {"oil_pct_lv2": 50},
                    "metrics_used": {"WTI.pct": 8.2},
                },
                {
                    "char_id": "CHAR_VILLAIN_002",
                    "faction": "VILLAIN",
                    "role": "PRIMARY_ANTAGONIST",
                    "appear": True,
                    "score": 95,
                    "threshold": 60,
                    "rank": 1,
                    "reasons": ["WTI pct >= 8 Oil Shock high trigger"],
                    "score_breakdown": {"wti_pct_lv2": 60},
                    "metrics_used": {"WTI.pct": 8.2},
                },
            ],
        },
    }


def test_character_selection_summary_extracts_reporting_fields():
    summary = character_selection_summary(_ctx())

    assert summary["character_selector_version"] == "character-appearance-v2"
    assert summary["character_selector_mode"] == "scored"
    assert summary["selected_hero_id"] == "CHAR_HERO_003"
    assert summary["selected_villain_id"] == "CHAR_VILLAIN_002"
    assert summary["top_hero_score"] == 105
    assert summary["top_villain_score"] == 95
    assert summary["neutral_guest_count"] == 1
    assert summary["character_selection_reason"] == "ONE_VS_ONE selected by score"


def test_character_selection_candidate_rows_flatten_candidates():
    rows = character_selection_candidate_rows("2026-06-03", "BATTLE", _ctx())

    assert len(rows) == 2
    hero = next(row for row in rows if row["faction"] == "HERO")
    villain = next(row for row in rows if row["faction"] == "VILLAIN")
    assert hero["selected"] is True
    assert villain["selected"] is True
    assert hero["score_breakdown"] == {"oil_pct_lv2": 50}
    assert villain["metrics_used"] == {"WTI.pct": 8.2}


def test_episode_asset_payload_excludes_character_snapshot_by_default(monkeypatch):
    monkeypatch.setenv("CHARACTER_SELECTION_ASSET_SNAPSHOT_ENABLED", "false")

    payload = _build_episode_asset_payload(
        "ICG-2026-06-03-001",
        _ctx(),
        {"title": "테스트", "panels": []},
    )

    assert "character_selection_json" not in payload
    assert "active_character_cards_json" not in payload
    assert payload["heroes_json"] == ["CHAR_HERO_003"]


def test_episode_asset_payload_includes_character_snapshot_when_enabled(monkeypatch):
    monkeypatch.setenv("CHARACTER_SELECTION_ASSET_SNAPSHOT_ENABLED", "true")

    payload = _build_episode_asset_payload(
        "ICG-2026-06-03-001",
        _ctx(),
        {"title": "테스트", "panels": []},
    )

    assert payload["character_selection_json"]["primary_hero"] == "CHAR_HERO_003"
    assert payload["active_character_cards_json"] == [{"char_id": "CHAR_HERO_003"}]


def test_character_selection_summary_includes_selected_villain_ids():
    from engine.persist.asset_writer import character_selection_summary

    summary = character_selection_summary({
        "character_selection": {
            "version": "character-appearance-v2",
            "primary_hero": "CHAR_HERO_001",
            "support_heroes": ["CHAR_HERO_002"],
            "primary_villain": "CHAR_VILLAIN_004",
            "support_villains": ["CHAR_VILLAIN_001"],
            "villains": ["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
            "neutral_guests": [],
            "all_candidates": [],
        }
    })

    assert summary["selected_villain_id"] == "CHAR_VILLAIN_004"
    assert summary["selected_villain_ids"] == ["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"]


def test_daily_analysis_update_strips_optional_summary_columns_in_one_retry(monkeypatch):
    calls: list[dict] = []

    class _Query:
        def __init__(self, payload: dict):
            self.payload = payload

        def eq(self, *_args):
            return self

        def execute(self):
            calls.append(dict(self.payload))
            if "character_selection" in self.payload:
                raise Exception(
                    "{'message': \"Could not find the 'character_selection' column "
                    "of 'daily_analysis' in the schema cache\", 'code': 'PGRST204'}"
                )
            if "top_hero_score" in self.payload:
                raise Exception(
                    "{'message': \"Could not find the 'top_hero_score' column "
                    "of 'daily_analysis' in the schema cache\", 'code': 'PGRST204'}"
                )
            return None

    class _Table:
        def update(self, payload: dict):
            return _Query(payload)

    monkeypatch.setattr(
        "engine.common.supabase_client.icg_table",
        lambda table_name: _Table(),
    )

    stripped = _update_daily_analysis_schema_compatible(
        "2026-06-30",
        {
            "analysis_ctx_json": {"event_type": "INTEL"},
            "character_selection": {"primary_hero": "CHAR_HERO_004"},
            "selected_hero_id": "CHAR_HERO_004",
            "top_hero_score": 88,
        },
    )

    assert stripped == [
        "character_selection",
        "selected_hero_id",
        "top_hero_score",
    ]
    assert len(calls) == 2
    assert calls[-1] == {"analysis_ctx_json": {"event_type": "INTEL"}}
