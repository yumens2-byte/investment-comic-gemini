from engine.narrative.continuity import build_continuity_bundle, bundle_from_episode_row


def _script():
    return {
        "date": "2026-06-05",
        "title": "전날의 균열",
        "logline": "변동성의 균열이 남았다.",
        "panels": [
            {"idx": 1, "panel_type": "COVER", "narration": "균열이 열렸다."},
            {"idx": 7, "panel_type": "AFTERMATH", "narration": "문은 아직 닫히지 않았다."},
            {"idx": 8, "panel_type": "DISCLAIMER", "narration": "투자 권유가 아닙니다."},
        ],
    }


def test_build_continuity_bundle_uses_final_non_disclaimer_panel_as_hook() -> None:
    bundle = build_continuity_bundle(
        "ICG-2026-06-05-001",
        "2026-06-05",
        {
            "event_type": "BATTLE",
            "scenario_type": "ONE_VS_ONE",
            "heroes": ["CHAR_HERO_001"],
            "villain_id": "CHAR_VILLAIN_002",
            "battle_result": {"outcome": "DRAW"},
        },
        _script(),
    )

    assert bundle["source_episode_id"] == "ICG-2026-06-05-001"
    assert bundle["final_panel_summary"] == "문은 아직 닫히지 않았다."
    assert bundle["next_hook"] == "문은 아직 닫히지 않았다."
    assert bundle["unresolved_threads"]


def test_bundle_from_episode_row_prefers_embedded_continuity() -> None:
    embedded = {"source_episode_id": "ICG-2026-06-04-001", "next_hook": "old hook"}
    row = {"episode_date": "2026-06-04", "episode_no": 1, "script_json": {"_continuity": embedded}}

    assert bundle_from_episode_row(row) == embedded


def test_load_previous_continuity_prefers_published_rows(monkeypatch) -> None:
    from engine.narrative.continuity import load_previous_continuity
    import sys

    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data

    class Table:
        def __init__(self):
            self.status = None

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, key, value):
            if key == "status":
                self.status = value
                calls.append(value)
            return self

        def lt(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            if self.status == "published":
                return Resp([
                    {
                        "episode_date": "2026-06-04",
                        "episode_no": 1,
                        "event_type": "BATTLE",
                        "status": "published",
                        "script_json": _script(),
                        "battle_json": {"outcome": "DRAW"},
                        "scenario_type": "ONE_VS_ONE",
                        "heroes_json": ["CHAR_HERO_001"],
                    }
                ])
            return Resp([])

    sb = sys.modules["engine.common.supabase_client"]
    monkeypatch.setattr(sb, "icg_table", lambda _name: Table())

    bundle = load_previous_continuity("2026-06-05")

    assert bundle is not None
    assert bundle["source_episode_id"] == "ICG-2026-06-04-001"
    assert calls == ["published"]
