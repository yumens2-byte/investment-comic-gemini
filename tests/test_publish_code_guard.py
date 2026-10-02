"""PR-05: scheduled publication waits for an attended run after publish-code changes."""
from scripts.publish_code_guard import GUARDED_PATHS, schedule_publish_allowed

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_unchanged_publish_code_allows_schedule():
    allowed, reason = schedule_publish_allowed(SHA, ["engine/image/prompt_builder.py"])
    assert allowed and reason.startswith("unchanged_since:")


def test_publish_code_change_blocks_schedule():
    allowed, reason = schedule_publish_allowed(SHA, ["engine/publish/claim_guard.py", "README.md"])
    assert not allowed and "engine/publish/claim_guard.py" in reason


def test_missing_evidence_blocks_schedule():
    assert schedule_publish_allowed(None, [])[0] is False
    assert schedule_publish_allowed("not-a-sha", [])[0] is False
    assert schedule_publish_allowed(SHA, None) == (False, "commit_history_unavailable")


def test_guarded_paths_cover_publication_contract():
    assert "engine/publish/" in GUARDED_PATHS
    assert "scripts/run_publish.py" in GUARDED_PATHS
    assert "docs/sql/narrative-publication-state.sql" in GUARDED_PATHS
