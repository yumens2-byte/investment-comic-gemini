from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPlan:
    primary: str
    fallbacks: tuple[str, ...]


ROUTING_TABLE = {
    "code_analysis": ModelPlan("chatgpt", ("claude", "gemini")),
    "requirements": ModelPlan("claude", ("chatgpt", "gemini")),
    "summary": ModelPlan("gemini", ("chatgpt", "claude")),
    "complex": ModelPlan("chatgpt", ("claude", "gemini")),
}


def select_model_plan(task_type: str, block_external: bool = False) -> ModelPlan:
    if block_external:
        return ModelPlan("blocked", tuple())
    return ROUTING_TABLE.get(task_type, ROUTING_TABLE["complex"])
