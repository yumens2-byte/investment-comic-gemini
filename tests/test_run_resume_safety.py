import pytest

from scripts.run_resume import _latest_episode_id, guard_resume_status


class _Resp:
    def __init__(self, data):
        self.data = data


class _EpisodeTable:
    def __init__(self, rows_by_status):
        self.rows_by_status = rows_by_status
        self._status = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        if key == "status":
            self._status = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Resp(self.rows_by_status.get(self._status, []))


def test_guard_resume_status_blocks_assembled_without_force() -> None:
    with pytest.raises(RuntimeError, match="--force"):
        guard_resume_status("assembled", force=False, allow_narrative_only=False)


def test_guard_resume_status_allows_force_for_assembled() -> None:
    guard_resume_status("assembled", force=True, allow_narrative_only=False)


def test_guard_resume_status_blocks_narrative_done_by_default() -> None:
    with pytest.raises(RuntimeError, match="allow-narrative-only"):
        guard_resume_status("narrative_done", force=True, allow_narrative_only=False)


def test_latest_episode_defaults_to_image_generated_only(monkeypatch) -> None:
    table = _EpisodeTable(
        {
            "image_generated": [],
            "assembled": [{"episode_date": "2026-06-04", "episode_no": 2}],
        }
    )
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    monkeypatch.setattr(sb, "icg_table", lambda _name: table)

    assert _latest_episode_id() is None


def test_latest_episode_can_include_narrative_only(monkeypatch) -> None:
    table = _EpisodeTable(
        {
            "image_generated": [],
            "narrative_done": [{"episode_date": "2026-06-05", "episode_no": 3}],
        }
    )
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    monkeypatch.setattr(sb, "icg_table", lambda _name: table)

    assert _latest_episode_id(allow_narrative_only=True) == "ICG-2026-06-05-003"
