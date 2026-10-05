"""The ONLY place allowed to import the ICG ``engine`` package (DR-3).

Allowed symbols (also the vendor list for the future repo split):
  engine.image.gemini_client: generate_panel
  engine.image.generation_guard: GenerationHold
  engine.assembly.pil_composer: compose_episode
  engine.narrative.claude_client: _extract_json, _build_messages_create_kwargs
Implemented in P1.
"""
