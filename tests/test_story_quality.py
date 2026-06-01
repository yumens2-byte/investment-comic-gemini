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
        "top_evidence": [
            {"id": "metric:VIX", "value": "VIX 15.7", "story_role": "volatility"}
        ]
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
