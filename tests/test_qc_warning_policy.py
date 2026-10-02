"""Default advisory QC, continued assembly and Telegram alert contracts (offline)."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from engine.quality.content_qc import require_content_ready, require_reviewed_sources
from engine.quality.contracts import QualityHold
from engine.quality.policy import advisory_qc, qc_finding, qc_is_strict
from scripts import notify_qc_warnings


@pytest.fixture
def advisory(monkeypatch, tmp_path):
    monkeypatch.delenv("ICG_QC_MODE")  # Verify production default, not just an explicit flag.
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_default_warning_preserves_hold_and_records_findings(advisory):
    script = {"_recovery_qc": {"status": "HOLD"}}
    row = {"error_message": "CONTENT_QC_HOLD:wrong shield"}
    require_content_ready(script, row)
    require_reviewed_sources(script, [])
    assert script["_recovery_qc"]["status"] == "HOLD"
    rows = [json.loads(s) for s in Path("output/qc_warnings.jsonl").read_text().splitlines()]
    assert [r["gate"] for r in rows] == ["content_review", "reviewed_sources"]
    assert all(r["run_id"] == "123" for r in rows)


def test_missing_review_continues_actual_assembly(advisory):
    from engine.assembly.pil_composer import compose_episode

    source = advisory / "P1.png"
    Image.new("RGB", (20, 20), "red").save(source)
    script = {"_recovery_qc": {"status": "HOLD"},
              "panels": [{"idx": 1, "panel_type": "TENSION", "key_text": ""}]}
    require_content_ready(script, {"error_message": "CONTENT_QC_HOLD:visual review pending"})
    require_reviewed_sources(script, [source])
    slides = compose_episode(script["panels"], [source], advisory / "slides", strict=True)
    assert len(slides) == 1 and slides[0].is_file()


def test_advisory_cannot_suppress_operational_exception(advisory):
    @advisory_qc("test")
    def broken():
        raise ConnectionError("DB unavailable")
    with pytest.raises(ConnectionError):
        broken()
    assert not Path("output/qc_warnings.jsonl").exists()


def test_publication_hold_remains_blocking(advisory):
    from engine.publish.claim_guard import require_no_publication_hold

    with pytest.raises(QualityHold, match="publication is unresolved"):
        require_no_publication_hold({"error_message": "PUBLISH_HOLD:token"})


def test_paid_call_hold_stays_blocking(advisory):
    from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard

    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-02/panels",
                                      panel=1, prompt="test", refs=[])
    guard._rpc = Mock(side_effect=GenerationHold("scope requires reconciliation"))
    with pytest.raises(GenerationHold):
        guard.reserve()


def test_dry_qc_logs_without_journal_or_telegram(advisory, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    qc_finding("test", "below score")
    sender = Mock()
    monkeypatch.setattr(notify_qc_warnings, "_send_telegram", sender)
    assert notify_qc_warnings.main() == 0
    assert not Path("output/qc_warnings.jsonl").exists()
    sender.assert_not_called()


def test_telegram_warning_deduplicates_filters_run_and_escapes_html(advisory, monkeypatch):
    qc_finding("content", "bad <shield> & shape")
    qc_finding("content", "bad <shield> & shape")
    monkeypatch.setenv("GITHUB_RUN_ID", "other")
    qc_finding("other", "not this run")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "test-channel")
    sender = Mock(return_value=False)
    monkeypatch.setattr(notify_qc_warnings, "_send_telegram", sender)
    assert notify_qc_warnings.main() == 0  # Alert failure does not fail the system.
    sender.assert_called_once()
    text = sender.call_args.args[2]
    assert "QC 경고 1건" in text and "&lt;shield&gt; &amp;" in text
    assert "not this run" not in text and "계속 진행" in text


def test_no_findings_no_telegram(advisory, monkeypatch):
    sender = Mock()
    monkeypatch.setattr(notify_qc_warnings, "_send_telegram", sender)
    assert notify_qc_warnings.main() == 0
    sender.assert_not_called()


def test_live_preflight_warning_is_not_lost_when_publish_does_not_run(advisory, monkeypatch):
    Path('output').mkdir()
    Path('output/publish-preflight.json').write_text(json.dumps({
        'mode': 'live_preflight', 'run_id': '123', 'qc_warnings': ['stale review']}))
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('TELEGRAM_FREE_CHANNEL_ID', 'test-channel')
    sender = Mock(return_value=True)
    monkeypatch.setattr(notify_qc_warnings, '_send_telegram', sender)
    assert notify_qc_warnings.main() == 0
    assert 'stale review' in sender.call_args.args[2]


@pytest.mark.parametrize("mode", ["", "typo"])
def test_invalid_policy_is_configuration_error(advisory, monkeypatch, mode):
    monkeypatch.setenv("ICG_QC_MODE", mode)
    with pytest.raises(ValueError, match="ICG_QC_MODE"):
        qc_is_strict()


def test_strict_mode_retains_review_gate(advisory, monkeypatch):
    monkeypatch.setenv("ICG_QC_MODE", "strict")
    with pytest.raises(QualityHold):
        require_content_ready({"_recovery_qc": {"status": "HOLD"}})


def test_legacy_strict_flags_do_not_block_warning_policy(advisory, monkeypatch):
    from scripts import run_market

    monkeypatch.setenv("CONTINUITY_STRICT_ENABLED", "true")
    monkeypatch.setenv("SERIAL_NARRATIVE_P0_ENABLED", "true")
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")
    assert run_market._production_quality_strict_enabled() is False
    assert run_market._validate_narrative_quality_inputs({})["evidence_count"] == 0
    assert run_market._quality_attempt_limit(continuity_strict=False, production_strict=False) == 1


def test_performance_failure_continues_with_real_image_input(advisory, monkeypatch):
    from engine.image import (
        gemini_client,
        performance_compiler,
        performance_validator,
        prompt_builder,
    )
    from engine.persist import asset_writer
    from scripts import run_market

    monkeypatch.setenv("PERFORMANCE_SPEC_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_QUALITY_MODE", "strict")
    monkeypatch.setattr(performance_compiler, "compile_episode_performance", lambda _: [])
    quality = SimpleNamespace(status="FAIL", score=10, issues=[SimpleNamespace(code="STATIC")],
                              model_dump=lambda: {"status": "FAIL"})
    monkeypatch.setattr(performance_validator, "validate_episode_performance", lambda *a: quality)
    prompt = SimpleNamespace(panel_idx=1, prompt_text="test", ref_image_paths=[])
    monkeypatch.setattr(prompt_builder, "build_for_episode", lambda *a, **kw: [prompt])
    monkeypatch.setattr(gemini_client, "generate_episode", lambda *a: ([Path("P1.png")], 0.01))
    patch = Mock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    run_market.step_image("2026-10-02", "ICG-2026-10-02-001", {},
                          {"panels": [{"idx": 1, "panel_type": "TENSION"}]}, Mock())
    assert patch.call_args.args[2]["status"] == "image_generated"
    assert patch.call_args.args[2]["performance_quality_json"]["status"] == "FAIL"


def test_video_motion_warning_does_not_regenerate_or_stop(advisory, monkeypatch):
    from engine.video import weekly_media as wm
    from tests.test_weekly_v2_media_render import (
        _FakeVeo,
        _install_media_fakes,
        _keyframed,
        _scenario,
    )

    veo = _FakeVeo()
    frozen = {"duration_sec": 4, "freeze_ratio": 0.8, "motion_score": 0.0, "frames": 96}
    _install_media_fakes(monkeypatch, veo, [frozen] * 4)
    result = wm.generate_shots(_scenario(), advisory, _keyframed(advisory), dry_run=False)
    assert len(result.shots) == 4 and len(veo.calls) == 4
    assert result.regenerations == 0
    assert result.motion[0]["freeze_ratio"] == 0.8


def test_all_live_workflows_notify_even_on_success(advisory):
    import yaml

    root = Path(__file__).resolve().parents[1]
    for name in ("run_market", "resume_episode", "publish_sns", "run_weekly_shorts",
                 "run_video_trailer", "publish_shorts"):
        workflow = yaml.safe_load((root / ".github/workflows" / f"{name}.yml").read_text())
        notifications = [s for job in workflow["jobs"].values() for s in job["steps"]
                         if s.get("name") == "Notify QC Warnings"]
        assert len(notifications) == 1
        assert notifications[0]["if"] == "always()"
        assert notifications[0]["continue-on-error"] is True


def test_release_score_remains_failed_evidence_without_stopping(advisory):
    from engine.quality.release import QualityReport

    report = QualityReport(content_hash="0" * 64, items=(), roles=(), checks={},
                           critical_findings=("wrong character",))
    assert report.approve() == 0
    assert report.critical_findings == ("wrong character",)
    assert report.checks == {}
    assert "overall score below 80" in Path("output/qc_warnings.jsonl").read_text()


def test_canon_quality_warning_does_not_reject_parseable_narrative(advisory):
    from engine.narrative.claude_client import _validate_canon

    (advisory / "config").mkdir()
    (advisory / "config/characters.yaml").write_text("heroes: {}\nvillains: {}\n")
    script = SimpleNamespace(panels=[SimpleNamespace(idx=1, characters=[
        SimpleNamespace(char_id="unregistered", role="villain")])])
    _validate_canon(script, scenario_type="NO_BATTLE")
    text = Path("output/qc_warnings.jsonl").read_text()
    assert "narrative_canon" in text and "unregistered" in text


def test_telegram_failure_workflow_steps_retained(advisory):
    import yaml

    root = Path(__file__).resolve().parents[1]
    for name in ("run_market", "resume_episode", "publish_sns"):
        workflow = yaml.safe_load((root / ".github/workflows" / f"{name}.yml").read_text())
        failure = [s for job in workflow["jobs"].values() for s in job["steps"]
                   if s.get("name") == "Notify Failure"]
        assert len(failure) == 1
        assert "failure()" in failure[0]["if"]
        assert failure[0]["run"] == "python -m scripts.notify_failure"


def test_video_visual_findings_continue_without_changing_source(advisory):
    from engine.video.shorts_pipeline import (
        ShortsScenario,
        enforce_canon_visuals,
        enforce_consistency,
    )
    from engine.video.weekly_v2 import validate_v2_scenario
    from tests.test_shorts_pipeline import _scenario_dict
    from tests.test_weekly_v2 import _facts, _scenario

    payload = _scenario_dict()
    for cut in payload['cuts']:
        cut['video_prompt'] = 'A generic figure waits quietly in an empty financial district.'
    shorts = ShortsScenario(**payload)
    original = shorts.model_dump()
    enforce_canon_visuals(shorts)
    enforce_consistency(shorts, outcome="different", hero_ids=[], villain_id="different")
    assert shorts.model_dump() == original
    weekly = _scenario(lambda p: p["shots"][0].update(
        motion_prompt="A quiet still scene with no action in an empty financial district."))
    validate_v2_scenario(weekly, _facts())
    warnings = Path("output/qc_warnings.jsonl").read_text()
    assert "video_canon" in warnings and "video_consistency" in warnings
    assert "video_scenario" in warnings


def test_video_episode_identity_still_blocks(advisory):
    from engine.video.shorts_pipeline import ConsistencyGuardError
    from engine.video.weekly_v2 import validate_v2_scenario
    from tests.test_weekly_v2 import _facts, _scenario

    with pytest.raises(ConsistencyGuardError, match="episode_id mismatch"):
        validate_v2_scenario(_scenario(), _facts(episode_id="other-episode"))


def test_disclaimer_qc_is_warning(advisory):
    from engine.publish.x_publisher import _guard_disclaimer

    _guard_disclaimer("No disclaimer")
    assert "x_disclaimer" in Path("output/qc_warnings.jsonl").read_text()
