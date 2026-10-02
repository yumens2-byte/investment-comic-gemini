"""Regression: the publication claim must build a valid, bounded PostgREST request."""
import pytest
from postgrest import SyncPostgrestClient

from engine.publish import claim_guard
from engine.quality.contracts import QualityHold


class _Capture(Exception):
    pass


def _client_capturing(monkeypatch, sink):
    client = SyncPostgrestClient("https://example.invalid/rest/v1", schema="icg")

    def table(name):
        builder = client.from_(name)
        original_update = builder.update

        def update(payload):
            query = original_update(payload)

            def execute():
                sink["params"] = str(query.request.params)
                raise _Capture()
            query.execute = execute
            return query
        builder.update = update
        return builder

    monkeypatch.setattr("engine.common.supabase_client.icg_table", table)


def _row(**extra):
    big = {"panels": [{"idx": i, "action": "가" * 3000} for i in range(1, 9)],
           "_reviewed_image_inputs": {"panels": ["x" * 8000] * 6}}
    return {"status": "assembled", "error_message": None, "script_json": big,
            "updated_at": "2026-10-02T15:57:05.136865+00:00", **extra}


def test_claim_does_not_send_script_json_filter(monkeypatch):
    sink = {}
    _client_capturing(monkeypatch, sink)
    with pytest.raises(_Capture):
        claim_guard.claim_publication(_row(), "2026-10-03", 1)
    assert "script_json" not in sink["params"]
    assert "updated_at=eq.2026-10-02T15%3A57%3A05.136865%2B00%3A00" in sink["params"]
    assert len(sink["params"]) < 2000


def test_claim_requires_row_version(monkeypatch):
    _client_capturing(monkeypatch, {})
    with pytest.raises(QualityHold):
        claim_guard.claim_publication(_row(updated_at=None), "2026-10-03", 1)
