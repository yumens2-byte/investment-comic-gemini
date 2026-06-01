from types import SimpleNamespace

from engine.image.gemini_client import (
    _calc_cost,
    _estimate_prompt_tokens,
    _extract_usage_tokens,
    _response_parts,
)


def test_extract_usage_tokens_from_snake_case_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=1200,
            candidates_token_count=340,
            total_token_count=1540,
        )
    )

    assert _extract_usage_tokens(response) == (1200, 340)


def test_extract_usage_tokens_from_camel_case_dict_and_total_fallback() -> None:
    response = {
        "usageMetadata": {
            "promptTokenCount": 200,
            "totalTokenCount": 260,
        }
    }

    assert _extract_usage_tokens(response) == (200, 60)


def test_calc_cost_uses_prompt_and_output_tokens() -> None:
    assert _calc_cost(1_000_000, 1_000_000) == 30.3


def test_response_parts_handles_missing_content_without_attribute_error() -> None:
    response = SimpleNamespace(candidates=[SimpleNamespace(content=None)])

    assert _response_parts(response) == []


def test_estimate_prompt_tokens_includes_reference_images() -> None:
    assert _estimate_prompt_tokens("abcd" * 10, [object(), object()]) == 10 + 516
