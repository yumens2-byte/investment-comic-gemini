import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from scripts.prepare_assembly_beta import select_source


def row(day="2026-10-20", run="123"):
    return {
        "episode_date": day,
        "episode_no": 1,
        "artifact_run_id": run,
        "script_json": {"date": day, "episode_id": f"ICG-{day}-001"},
    }


def test_latest_available_source_skips_expired_artifact_without_mutating_inputs():
    rows = [row(), row("2026-10-19", "122")]
    before = deepcopy(rows)
    source = select_source(rows, lambda run: [{"name": f"episode-{run}", "expired": run == "123"}])
    assert source["run_id"] == "122"
    assert rows == before


def test_unknown_artifact_does_not_count_as_available():
    with pytest.raises(RuntimeError, match="No available"):
        select_source([row()], lambda run: [{"name": "wrong-name", "expired": False}])


def test_narrative_identity_mismatch_fails_closed():
    source = row()
    source["script_json"]["episode_id"] = "ICG-2026-10-19-001"
    with pytest.raises(ValueError, match="identity"):
        select_source([source], lambda run: [{"name": f"episode-{run}", "expired": False}])


def test_prepare_reads_services_only_and_stores_narrative_privately(monkeypatch, tmp_path):
    from scripts import prepare_assembly_beta as module

    for key, value in {
        "GITHUB_REPOSITORY": "owner/repo",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "test-only",
        "GH_TOKEN": "test-only",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
    }.items():
        monkeypatch.setenv(key, value)
    replies = [
        Mock(status_code=200, json=Mock(return_value=[row()])),
        Mock(
            status_code=200,
            json=Mock(return_value={"artifacts": [{"name": "episode-123", "expired": False}]}),
        ),
    ]
    get = Mock(side_effect=replies)
    monkeypatch.setattr(module.requests, "get", get)
    module.main()
    assert get.call_count == 2
    assert (tmp_path / "assembly-beta-source.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "outputs").read_text() == "episode_id=ICG-2026-10-20-001\nrun_id=123\n"


@pytest.fixture
def replay(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    episode = "ICG-2026-10-20-001"
    root = Path("output/episodes/2026-10-20")
    (root / "panels").mkdir(parents=True)
    Image.new("RGB", (128, 160), "red").save(root / "panels/P1.png")
    script = {
        "episode_id": episode,
        "date": "2026-10-20",
        "panels": [
            {"idx": 1, "panel_type": "COVER", "key_text": "Cover", "narration": "Narrative"},
            {"idx": 2, "panel_type": "TEXT_CARD", "key_text": "Market", "narration": "Facts"},
            {
                "idx": 3,
                "panel_type": "DISCLAIMER",
                "key_text": "Disclaimer",
                "narration": "Fiction",
            },
        ],
    }
    manifest = {
        "episode_id": episode,
        "panels": [
            {"panel_idx": 1, "path": str(root / "panels/P1.png")},
            {"panel_idx": 2, "path": None},
            {"panel_idx": 3, "path": None},
        ],
    }
    (root / f"{episode}_images.json").write_text(json.dumps(manifest))
    private = tmp_path / "private-script.json"
    private.write_text(json.dumps(script))
    monkeypatch.setattr(
        sys, "argv", ["run_assembly_artifact_beta", "--episode", episode, "--script", str(private)]
    )
    return root, episode, manifest


def test_replay_accepts_current_artifact_without_embedded_script(replay):
    from scripts.run_assembly_artifact_beta import main

    main()
    report = json.loads(Path("output/assembly-beta/report.json").read_text())
    assert report["slides"] == 3 and report["source_images_verified"] == 1
    assert report["database_writes"] == report["paid_calls"] == report["publishes"] == 0


def test_replay_rejects_incomplete_manifest_before_composition(replay):
    from scripts.run_assembly_artifact_beta import main

    root, episode, manifest = replay
    manifest["panels"].pop()
    (root / f"{episode}_images.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="coverage"):
        main()
    assert not Path("output/assembly-beta/slides").exists()
