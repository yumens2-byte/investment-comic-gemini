import pytest

from engine.narrative.story_quality import StoryGroundingError, validate_story_grounding


def _script_with_algo_claim() -> dict:
    return {
        "panels": [
            {
                "idx": 2,
                "market_ref": "알고 트레이딩 비중 이상 급증 감지",
                "narration": "시장 회로가 흔들렸다.",
            }
        ]
    }


def test_story_grounding_flags_unsupported_algo_trading_claim() -> None:
    context_pack = {
        "top_evidence": [{"id": "metric:VIX", "value": "VIX 15.7", "story_role": "volatility"}]
    }

    warnings = validate_story_grounding(_script_with_algo_claim(), context_pack)

    assert warnings
    assert "algo-trading" in warnings[0]


def test_story_grounding_raises_in_strict_mode() -> None:
    with pytest.raises(StoryGroundingError):
        validate_story_grounding(_script_with_algo_claim(), {"top_evidence": []}, strict=True)


def test_story_grounding_allows_when_algo_evidence_is_supplied() -> None:
    context_pack = {
        "top_evidence": [
            {
                "id": "news:algo-volume",
                "headline_summary": "알고 트레이딩 거래 비중 급증이 확인됨",
                "story_role": "algo trading volume evidence",
            }
        ]
    }

    assert validate_story_grounding(_script_with_algo_claim(), context_pack, strict=True) == []


def test_story_continuity_flags_missing_previous_hook_payoff() -> None:
    from engine.narrative.story_quality import StoryContinuityError, validate_story_continuity

    script = {
        "panels": [
            {"idx": 1, "narration": "새로운 전투가 시작됐다.", "key_text": "돌격!"},
            {"idx": 2, "narration": "VIX가 흔들렸다."},
        ]
    }
    context = {"previous_episode": {"next_hook": "검은 문은 아직 닫히지 않았다"}}

    with pytest.raises(StoryContinuityError):
        validate_story_continuity(script, context, strict=True)


def test_story_continuity_passes_when_opening_mentions_previous_hook() -> None:
    from engine.narrative.story_quality import validate_story_continuity

    script = {
        "panels": [
            {"idx": 1, "narration": "검은 문은 아직 닫히지 않았고, 오늘의 VIX가 그 틈을 흔들었다."}
        ]
    }
    context = {"previous_episode": {"next_hook": "검은 문은 아직 닫히지 않았다"}}
    plan = {"panel_beats": [{"panel_idx": 1, "must_reference_previous": True}]}

    assert validate_story_continuity(script, context, plan, strict=True) == []
