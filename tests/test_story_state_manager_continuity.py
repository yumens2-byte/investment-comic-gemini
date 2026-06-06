from engine.character.story_state_manager import DEFAULT_STORY_STATE, load_story_state


class _Resp:
    def __init__(self, data):
        self.data = data


class _DailyAnalysisTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def lt(self, key, value):
        self.filters.append(("lt", key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Resp(self.rows)


def test_load_story_state_uses_latest_prior_non_null_state(monkeypatch) -> None:
    rows = [
        {"analysis_date": "2026-06-04", "story_state_json": None},
        {"analysis_date": "2026-06-01", "story_state_json": {"arc_id": "arc_prior", "arc_episode": 7}},
    ]
    table = _DailyAnalysisTable(rows)
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    monkeypatch.setattr(sb, "icg_table", lambda _name: table)

    state = load_story_state("2026-06-05")

    assert state["arc_id"] == "arc_prior"
    assert ("lt", "analysis_date", "2026-06-05") in table.filters


def test_load_story_state_falls_back_when_no_prior_state(monkeypatch) -> None:
    table = _DailyAnalysisTable([])
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    monkeypatch.setattr(sb, "icg_table", lambda _name: table)

    assert load_story_state("2026-06-05")["arc_id"] == DEFAULT_STORY_STATE["arc_id"]
