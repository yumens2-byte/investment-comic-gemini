"""Paid-generation guards: exact identity, terminal states and no unsafe fallback."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from engine.video import weekly_media as weekly
from scripts import run_market as pipeline


def table_mock(monkeypatch, rows=None, error=None):
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    table = MagicMock()
    for method in ("select", "eq", "order", "limit"):
        getattr(table, method).return_value = table
    table.execute.return_value = SimpleNamespace(data=rows)
    if error:
        table.execute.side_effect = error
    monkeypatch.setattr(sb, "icg_table", lambda name: table)
    return table


@pytest.mark.parametrize("status", ["published", "assembled", "image_generated"])
def test_terminal_status_cannot_be_forced(monkeypatch, status):
    monkeypatch.setenv("FORCE_RUN", "true")
    table = table_mock(monkeypatch, [{"episode_no": 7, "status": status}])
    with pytest.raises(RuntimeError, match="safety check failed"):
        pipeline._assert_generation_allowed("2026-10-01", "ICG-2026-10-01-007")
    assert table.eq.call_args_list[0].args == ("episode_date", "2026-10-01")
    assert table.eq.call_args_list[1].args == ("episode_no", 7)


@pytest.mark.parametrize("rows", [None, [{"status": ""}], [{}, {}]])
def test_invalid_status_lookup_blocks(monkeypatch, rows):
    table_mock(monkeypatch, rows)
    with pytest.raises(RuntimeError):
        pipeline._assert_generation_allowed("2026-10-01", "ICG-2026-10-01-007")


def test_lookup_failure_blocks_identity_and_generation(monkeypatch):
    table_mock(monkeypatch, error=ConnectionError("DB unavailable"))
    with pytest.raises(RuntimeError):
        pipeline._make_episode_id("2026-10-01")
    with pytest.raises(RuntimeError):
        pipeline._assert_generation_allowed("2026-10-01", "ICG-2026-10-01-001")


def test_published_identity_cannot_increment_around_guard(monkeypatch):
    table_mock(monkeypatch, [{"episode_no": 7, "status": "published"}])
    assert pipeline._make_episode_id("2026-10-01") == "ICG-2026-10-01-007"


def test_empty_new_episode_allowed(monkeypatch):
    table_mock(monkeypatch, [])
    pipeline._assert_generation_allowed("2026-10-01", "ICG-2026-10-01-001")


def test_main_blocks_before_all_stage_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "false")
    import sys

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "all", "--date", "2026-10-01"])
    table_mock(monkeypatch, [{"episode_no": 7, "status": "published"}])
    mutations = [MagicMock(), MagicMock()]
    monkeypatch.setattr(pipeline, "step_data", mutations[0])
    monkeypatch.setattr(pipeline, "step_analysis", mutations[1])
    with pytest.raises(SystemExit):
        pipeline.main()
    assert all(not mutation.called for mutation in mutations)


@pytest.mark.parametrize("paths", [[], [None], [Path("valid.png"), None]])
def test_image_failure_never_marks_generated(monkeypatch, tmp_path, paths):
    from engine.image import gemini_client, prompt_builder
    from engine.persist import asset_writer

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompt_builder, "build_for_episode", lambda *a, **kw: [])
    monkeypatch.setattr(gemini_client, "generate_episode", lambda *a: (paths, 0.0))
    patch = MagicMock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    with pytest.raises(RuntimeError, match="incomplete image"):
        pipeline.step_image(
            "2026-10-01", "ICG-2026-10-01-001", {"event_type": "CRISIS"}, {}, MagicMock()
        )
    patch.assert_not_called()


@pytest.mark.parametrize("failure", [True, False])
def test_weekly_missing_refs_never_calls_paid_sdk(monkeypatch, tmp_path, failure):
    from engine.image import gemini_client, ref_loader

    paid = MagicMock()
    monkeypatch.setattr(gemini_client, "generate_panel", paid)
    refs = MagicMock(return_value=[])
    if failure:
        refs.side_effect = ValueError("canon mismatch")
    monkeypatch.setattr(ref_loader, "get_refs_for_panel", refs)
    scenario = SimpleNamespace(
        shots=[SimpleNamespace(seq=1, cast=["CHAR_HERO_001"], keyframe_prompt="action")]
    )
    with pytest.raises(weekly.WeeklyMediaError, match="REF validation"):
        weekly.generate_keyframes(scenario, tmp_path, weekly.V2MediaResult(), dry_run=False)
    paid.assert_not_called()


def test_video_retry_hardcap_prevents_sdk_call(tmp_path):
    client = MagicMock()
    with pytest.raises(weekly.WeeklyMediaError):
        weekly._generate_one_shot(
            client,
            SimpleNamespace(seq=1),
            tmp_path / "kf.png",
            tmp_path / "s.mp4",
            10**9,
            weekly.V2MediaResult(),
        )
    client.generate_image_to_video.assert_not_called()


def test_motion_environment_hardcap_prevents_sdk_init(monkeypatch, tmp_path):
    from engine.video import veo_client

    client = MagicMock()
    monkeypatch.setattr(veo_client, "VeoClient", client)
    monkeypatch.setenv("WEEKLY_MOTION_REGEN_MAX", "999999999")
    scenario = SimpleNamespace(shots=[SimpleNamespace(seq=1)])
    result = weekly.V2MediaResult(keyframes=[tmp_path / "kf.png"])
    with pytest.raises(weekly.WeeklyMediaError, match="hard limit"):
        weekly.generate_shots(scenario, tmp_path, result, dry_run=False)
    client.assert_not_called()


def test_unresolved_publish_hold_blocks_generation(monkeypatch):
    table_mock(
        monkeypatch,
        [{"episode_no": 7, "status": "persisted", "error_message": "PUBLISH_HOLD:token"}],
    )
    with pytest.raises(RuntimeError):
        pipeline._assert_generation_allowed("2026-10-01", "ICG-2026-10-01-007")


@pytest.mark.parametrize("threshold", ["nan", "inf", "-1", "2"])
def test_motion_threshold_cannot_bypass_quality(monkeypatch, tmp_path, threshold):
    from engine.video import veo_client
    client = MagicMock()
    monkeypatch.setattr(veo_client, "VeoClient", client)
    monkeypatch.setenv("WEEKLY_FREEZE_MAX", threshold)
    scenario = SimpleNamespace(shots=[SimpleNamespace(seq=1)])
    result = weekly.V2MediaResult(keyframes=[tmp_path / "kf.png"])
    with pytest.raises(weekly.WeeklyMediaError, match="freeze threshold"):
        weekly.generate_shots(scenario, tmp_path, result, dry_run=False)
    client.assert_not_called()


@pytest.mark.parametrize("rows", [None, [{"episode_no": 0, "status": "persisted"}], [{"episode_no": True, "status": "persisted"}], [{"episode_no": 7}]])
def test_invalid_stored_identity_blocks(monkeypatch, rows):
    table_mock(monkeypatch, rows)
    with pytest.raises(RuntimeError):
        pipeline._make_episode_id("2026-10-01")


def test_successful_image_patch_uses_exact_episode(monkeypatch, tmp_path):
    from engine.image import gemini_client, prompt_builder
    from engine.persist import asset_writer
    monkeypatch.chdir(tmp_path)
    prompts = [SimpleNamespace(panel_idx=1, prompt_text="action", ref_image_paths=[])]
    monkeypatch.setattr(prompt_builder, "build_for_episode", lambda *a, **kw: prompts)
    monkeypatch.setattr(gemini_client, "generate_episode", lambda *a: ([Path("valid.png")], 0.01))
    patch = MagicMock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    pipeline.step_image("2026-10-01", "ICG-2026-10-01-007", {"event_type": "CRISIS"},
                        {"panels": [{"idx": 1, "panel_type": "TENSION"}]}, MagicMock())
    assert patch.call_args.args[:2] == ("2026-10-01", 7)


def test_patch_by_episode_scopes_optional_retry(monkeypatch):
    from engine.persist import asset_writer
    table = table_mock(monkeypatch, [])
    table.update.return_value = table
    table.execute.side_effect = [Exception("missing optional"), SimpleNamespace(data=[])]
    monkeypatch.setattr(asset_writer, "extract_missing_column", lambda exc: "performance_quality_json")
    asset_writer.patch_by_episode("2026-10-01", 7, {"status": "image_generated", "performance_quality_json": {}}, optional_fields=frozenset({"performance_quality_json"}))
    assert all(call.args[0] in {"episode_date", "episode_no"} for call in table.eq.call_args_list)
    assert table.update.call_args_list[-1].args == ({"status": "image_generated"},)
