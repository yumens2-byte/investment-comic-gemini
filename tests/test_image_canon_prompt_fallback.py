from engine.image.prompt_builder import build_panel_prompt


def test_image_prompt_uses_local_canon_design_when_notion_missing(monkeypatch):
    monkeypatch.delenv("NOTION_REF_PROMPTS_ID", raising=False)

    prompt = build_panel_prompt(
        {
            "idx": 1,
            "panel_type": "BATTLE",
            "setting": "Oil market arena",
            "action": "Hero punches through an oil shock wave",
            "key_text": "버텨!",
            "narration": "유가 충격이 전장을 덮친다.",
            "characters": [
                {"char_id": "CHAR_HERO_003", "role": "hero", "position": "LEFT"}
            ],
        }
    )

    assert "LOCAL CANON DESIGN" in prompt
    assert "oil candle" in prompt
    assert "Forbidden Visuals" in prompt
