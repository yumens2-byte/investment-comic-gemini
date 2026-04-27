from app.ai.model_router import select_model_plan


def test_code_analysis_route() -> None:
    plan = select_model_plan("code_analysis")
    assert plan.primary == "chatgpt"
    assert plan.fallbacks == ("claude", "gemini")


def test_block_external_route() -> None:
    plan = select_model_plan("summary", block_external=True)
    assert plan.primary == "blocked"
    assert plan.fallbacks == tuple()
