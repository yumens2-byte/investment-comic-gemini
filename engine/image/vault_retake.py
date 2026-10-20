"""Offline P3–P6 correction brief for the debt/vault storyboard.

Changes visual action/setting only. Registration, generation and approval are
separate human gates; this module cannot call a provider or write to a database.
"""

from copy import deepcopy

from engine.image.generation_guard import GenerationHold
from engine.image.scene_performance import episode_specs, text_hash

_FACTS = {
    3: "debt_pressure_and_defensive_structure",
    4: "draw_and_balanced_pressure",
    5: "btc_signal_and_sealed_vault",
    6: "unnoticed_shield_crack_and_unresolved_standoff",
}

_BRIEFS = {
    3: (
        "Iron Securities Nuna bends her front knee deeply and lowers her hips behind her left forearm "
        "shield, with her rear foot planted farther back. Her right hand holds the rifle downward. "
        "Her shoulders rotate toward a growing lattice of interlinked debt forms at the right. "
        "The lattice is visibly separate from Debt Titan, who remains deeper at the right. "
        "A separate protective outline retains its shape beside the lattice. Her cape trails left.",
        "The same vault corridor, with a clearly visible debt lattice and intact protective outline "
        "on separate depth planes. The lower floor area is reserved for captions.",
        dict(
            shot_size="FS",
            view_angle="THREE_QUARTER",
            elevation="LOW",
            roll_degrees=0,
            focal_subject="deeply bent front knee and leading left forearm polygonal shield",
            depth_layers="leading shield and bent knee, heroine, distinct debt lattice, distant Titan",
            full_body_required=True,
        ),
    ),
    4: (
        "Iron Securities Nuna pivots sideways around one planted foot, shoulders and hips rotating "
        "together as her left forearm shield leads. The other foot shifts laterally and her cape "
        "curves behind the turn. Her right hand keeps the rifle lowered. The debt lattice and "
        "protective outline remain separate and equal in scale and brightness. Debt Titan remains "
        "farther right; the balanced standoff remains unresolved.",
        "The same vault corridor with a debt lattice and protective outline of equal visual weight. "
        "Diagonal floor lines support the pivot while the lower caption area remains uncluttered.",
        dict(
            shot_size="MWS",
            view_angle="THREE_QUARTER",
            elevation="EYE",
            roll_degrees=12,
            focal_subject="the sideways pivot, rotating shoulders and trailing cape",
            depth_layers="cape at left, heroine midground, two distinct balanced structures and Titan deeper right",
            full_body_required=False,
        ),
    ),
    5: (
        "Tight close-up of Iron Securities Nuna face and upper shoulder as she turns toward a small "
        "golden circular liquidity signal beyond her right shoulder. The signal floats near the "
        "sealed vault in the background, separated from her silhouette by a visible dark gap. "
        "Soft reflected golden light crosses her eyes and cheek while one strand of hair follows "
        "the turn. Her shield and rifle stay entirely below the crop. The vault remains sealed.",
        "The same vault corridor. A small unlabelled environmental signal floats beside the "
        "distant closed vault, never on the heroine or her shield. Face and signal occupy the upper image area.",
        dict(
            shot_size="CU",
            view_angle="THREE_QUARTER",
            elevation="EYE",
            roll_degrees=0,
            focal_subject="eyes and cheek reacting to reflected light; weapons below crop",
            depth_layers="face in foreground, visible dark gap, small separate signal and sealed vault in background",
            full_body_required=False,
        ),
    ),
    6: (
        "Extreme close-up of the intact amber-gold polygonal shield on Iron Securities Nuna left "
        "forearm. Several fine branching hairline cracks cross an uninterrupted unlabelled surface "
        "under grazing light. The cracks form the sharpest detail above the caption area. A section "
        "of the original polygonal rim remains visible. Her face and rifle stay outside the crop. "
        "She remains unaware of the cracks; the distant vault stays sealed and the standoff unresolved.",
        "A shield-surface detail in the same vault corridor. Grazing side light reveals fine cracks "
        "while the sealed vault is only a small softly blurred background shape.",
        dict(
            shot_size="ECU",
            view_angle="DETAIL",
            elevation="PROP",
            roll_degrees=0,
            focal_subject="fine branching cracks on the intact unlabelled shield above the caption area",
            depth_layers="shield surface and polygonal rim in foreground, small blurred sealed vault behind",
            full_body_required=False,
        ),
    ),
}


def repair_vault_brief(script: dict) -> dict:
    """Return a new unapproved brief; reject unrelated stories rather than invent facts."""
    specs = episode_specs(script)
    for idx, fact in _FACTS.items():
        if idx not in specs or fact not in specs[idx].required_story_facts:
            raise GenerationHold(f"P{idx} vault retake requires matching story facts")
        if specs[idx].motion.subject_id != "CHAR_HERO_002":
            raise GenerationHold("Vault retake requires the approved heroine")
    result = deepcopy(script)
    # Remove provider approval. Source assembly metadata stays as provenance for
    # the unchanged SQL narrative contract; its old script hash cannot authorize
    # these changed actions/settings (validate_manifest rejects it).
    for key in (
        "_reviewed_image_inputs",
        "_generation_revision",
    ):
        result.pop(key, None)
    for panel in result["panels"]:
        idx = panel["idx"]
        if idx not in _BRIEFS:
            continue
        action, setting, camera = _BRIEFS[idx]
        panel.update(action=action, setting=setting)
        spec = result["_scene_performance_v2"][str(idx)]
        spec.update(
            action_sha256=text_hash(action), setting_sha256=text_hash(setting), camera=camera.copy()
        )
        visible = ["CHAR_HERO_002"] if idx in {5, 6} else spec["story_cast"][:]
        spec.update(
            visible_cast=visible,
            must_show_cast=visible[:],
            offscreen_cast=[cid for cid in spec["story_cast"] if cid not in visible],
        )
        family, phase = {
            3: ("BRACE", "REACTION"),
            4: ("PIVOT", "ACTION"),
            5: ("TURN", "REACTION"),
            6: ("AFTERMATH_DETAIL", "RECOVERY"),
        }[idx]
        spec["motion"].update(family=family, phase=phase)
        if idx == 3:
            spec["motion"].update(
                support="deeply bent front knee and rear foot planted farther back",
                weight="low over the front leg",
                torso="hips and shoulders rotate behind the left shield",
                target="separate expanding interlinked debt lattice",
            )
        elif idx == 4:
            spec["motion"].update(family="PIVOT", phase="ACTION")
        elif idx == 5:
            spec["motion"].update(
                target_kind="DISPLAY",
                target="small environmental signal near the distant vault beyond the shoulder",
            )
        elif idx == 6:
            spec["motion"].update(
                target_kind="PROP",
                target="unlabelled intact polygonal shield surface with fine cracks",
                support="left forearm supports the shield; body remains outside the detail crop",
                weight="retained in the offscreen grounded stance",
                torso="outside this detail crop",
                gaze="toward the distant vault outside this crop",
                secondary_motion="grazing light reveals fine cracks on the intact surface",
            )
        spec["review_evidence"] = (
            "Correction brief based on observed pose, signal separation and shield continuity defects; "
            "new generation approval and actual image review remain pending."
        )
    episode_specs(result)
    return result
