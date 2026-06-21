import sys

from engine.arc.arc_state_engine import save_arc_state


class _ArcStateTable:
    def __init__(self, calls):
        self.calls = calls

    def upsert(self, payload, on_conflict):
        self.calls.append(dict(payload))
        return self

    def execute(self):
        if len(self.calls) == 1:
            raise RuntimeError(
                "{'message': \"Could not find the 'zero_block_just_appeared' column of "
                "'arc_state' in the schema cache\", 'code': 'PGRST204'}"
            )
        return None


def test_save_arc_state_retries_without_missing_optional_schema_column(monkeypatch):
    sb = sys.modules["engine.common.supabase_client"]
    calls = []
    monkeypatch.setattr(sb, "icg_table", lambda name: _ArcStateTable(calls))

    ok = save_arc_state(
        {
            "active_villain": "CHAR_VILLAIN_004",
            "arc_day": 2,
            "arc_tension": 30,
            "zero_block_just_appeared": False,
        }
    )

    assert ok is True
    assert len(calls) == 2
    assert "zero_block_just_appeared" in calls[0]
    assert "zero_block_just_appeared" not in calls[1]
    assert calls[1]["id"] == 1
