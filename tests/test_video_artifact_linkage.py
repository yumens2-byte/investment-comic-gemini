from __future__ import annotations

import scripts.resolve_episode as resolve_episode
from scripts.run_video_trailer import _safe_video_assets_update, _safe_video_assets_upsert


class _FakeExecute:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc

    def execute(self):
        if self.exc:
            raise self.exc
        return self.response


class _FakeTable:
    def __init__(self, parent):
        self.parent = parent

    def upsert(self, payload, on_conflict=None):
        self.parent.calls.append(("upsert", payload, on_conflict))
        exc = self.parent.exceptions.pop(0) if self.parent.exceptions else None
        return _FakeExecute(response={"ok": True}, exc=exc)

    def update(self, payload):
        self.parent.calls.append(("update", payload, None))
        exc = self.parent.exceptions.pop(0) if self.parent.exceptions else None
        return _FakeUpdateExecute(self.parent, exc=exc)


class _FakeUpdateExecute(_FakeExecute):
    def __init__(self, parent, exc: Exception | None = None):
        super().__init__(response={"ok": True}, exc=exc)
        self.parent = parent

    def eq(self, column, value):
        self.parent.calls.append(("eq", column, value))
        return self


class _FakeSupabase:
    def __init__(self, exceptions=None):
        self.exceptions = list(exceptions or [])
        self.calls = []

    def schema(self, schema_name):
        self.calls.append(("schema", schema_name, None))
        return self

    def table(self, table_name):
        self.calls.append(("table", table_name, None))
        return _FakeTable(self)


def test_resolve_episode_does_not_scan_repository_artifacts():
    source = resolve_episode._lookup_video_run_id.__code__.co_names

    assert "urlopen" not in source
    assert "Request" not in source


def test_safe_video_assets_upsert_retries_without_artifact_run_id_on_old_schema():
    sb = _FakeSupabase([Exception("column artifact_run_id does not exist")])

    _safe_video_assets_upsert(
        sb,
        {"episode_id": "ICG-2026-06-21-001", "artifact_run_id": "123"},
        context="test",
    )

    upsert_payloads = [call[1] for call in sb.calls if call[0] == "upsert"]
    assert upsert_payloads[0]["artifact_run_id"] == "123"
    assert "artifact_run_id" not in upsert_payloads[1]


def test_safe_video_assets_update_retries_without_artifact_run_id_on_old_schema():
    sb = _FakeSupabase([Exception("Could not find artifact_run_id column in schema cache")])

    _safe_video_assets_update(
        sb,
        "ICG-2026-06-21-001",
        {"cut1_video_uri": "output/videos/x/cut1.mp4", "artifact_run_id": "123"},
        context="test",
    )

    update_payloads = [call[1] for call in sb.calls if call[0] == "update"]
    assert update_payloads[0]["artifact_run_id"] == "123"
    assert "artifact_run_id" not in update_payloads[1]
