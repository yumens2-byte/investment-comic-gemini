"""Validate incident recovery preparation offline against canonical reference bytes."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

from engine.image import gemini_client
from scripts.prepare_image_recovery import prepare, validate_candidate


def test_oct21_recovery_scenes_prepare_without_paid_or_db_calls(monkeypatch):
    scenes = json.loads(Path("docs/incidents/2026-10-21-reviewed-scenes.json").read_text())
    provider = Mock(side_effect=AssertionError("paid calls forbidden"))
    db = Mock(side_effect=AssertionError("production DB forbidden"))
    monkeypatch.setattr(gemini_client, "_get_client", provider)
    monkeypatch.setattr("engine.common.supabase_client.get_client", db)
    panels = []
    for idx in range(1, 9):
        cast = [] if idx > 6 else [{"char_id": "CHAR_HERO_002", "role": "hero", "form": "form1"}]
        if idx <= 6 and idx != 2:
            cast.append({"char_id": "CHAR_VILLAIN_001", "role": "villain", "form": None})
        panels.append({"idx": idx, "panel_type": "BATTLE" if idx <= 6 else
                       "TEXT_CARD" if idx == 7 else "DISCLAIMER",
                       "action": "original action", "setting": "original setting",
                       "characters": cast, "narration": "Public story evidence retained."})
    source = {"episode_id": "ICG-2026-10-21-001", "date": "2026-10-21",
              "_generation_revision": 1, "_state_candidate": {"version": "state-candidate-1"},
              "panels": panels, "next_hook": "The inner shield crack remains unknown."}
    original = copy.deepcopy(source)
    candidate = prepare(source, scenes, 2, actor="reviewer",
                        note="Reviewed non-contact scenes retain cast, shield clue and public story.")
    validate_candidate(candidate)
    assert source == original
    assert candidate["_state_candidate"] == source["_state_candidate"]
    assert candidate["next_hook"] == source["next_hook"]
    assert candidate["panels"][6:] == source["panels"][6:]
    assert len(candidate["_reviewed_image_inputs"]["panels"]) == 6
    for before, after in zip(source["panels"], candidate["panels"]):
        assert before["characters"] == after["characters"]
        assert before["narration"] == after["narration"]
    assert all(item["refs"] and len(item["refs"]) == len(item["ref_sha256"])
               for item in candidate["_reviewed_image_inputs"]["panels"])
    provider.assert_not_called()
    db.assert_not_called()
