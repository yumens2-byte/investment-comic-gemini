"""Human-reviewed quality retakes; uses the existing durable cost/attempt ledger."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from pathlib import Path, PurePosixPath

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.scene_performance import episode_specs, payload_hash, rhythm_report
from engine.publish.manifest import script_hash


def rpc(name: str, params: dict) -> dict:
    from engine.common.supabase_client import get_client, get_schema

    result = get_client().schema(get_schema()).rpc(name, params).execute().data
    if not isinstance(result, dict) or result.get("hold"):
        raise GenerationHold(
            str(result.get("hold")) if isinstance(result, dict) else "Invalid quality receipt"
        )
    return result


def prepare(
    source: dict,
    candidate: dict,
    base_manifest: list[dict],
    *,
    revision: int,
    panels: list[int],
    base_run_id: str,
    base_selection_version: int = 0,
    max_cost_usd: float = 0.30,
) -> dict:
    """Offline preparation, no database writes or paid calls. Freeze final prompts."""
    from engine.image.prompt_builder import build_for_episode
    from engine.image.reviewed_inputs import reviewed_panel_prompts

    if (
        type(revision) is not int
        or not 2 <= revision <= 100
        or str(revision) != os.environ.get("ICG_GENERATION_REVISION")
        or not base_run_id.isascii()
        or not base_run_id.isdigit()
        or not panels
        or len(set(panels)) != len(panels)
    ):
        raise GenerationHold("Explicit revision, source artifact and unique panels required")
    candidate = deepcopy(candidate)
    candidate.pop("_reviewed_image_inputs", None)
    candidate.pop("_scene_contracts", None)
    candidate["_generation_revision"] = revision
    specs = episode_specs(candidate)
    if not specs or not set(panels) <= set(specs):
        raise GenerationHold("Complete performance specs and valid paid panel selection required")

    # Quality changes only visual action/setting; all other story fields are immutable.
    def story(s):
        return {
            k: (
                [{a: b for a, b in p.items() if a not in {"action", "setting"}} for p in v]
                if k == "panels"
                else v
            )
            for k, v in s.items()
            if k
            not in {
                "_reviewed_image_inputs",
                "_scene_contracts",
                "_scene_performance_v2",
                "_generation_revision",
            }
        }

    if story(source) != story(candidate):
        raise GenerationHold("Quality retake cannot change narrative or cast")
    prompts = build_for_episode(candidate)
    items = []
    scope = f"output/episodes/{candidate['date']}/panels"
    for pp in prompts:
        if pp.panel_idx not in specs:
            continue
        guard = ProductionGenerationGuard(
            scope=scope,
            panel=pp.panel_idx,
            prompt=pp.prompt_text + "\n[model=gemini-2.5-flash-image;aspect=4:5]",
            refs=pp.ref_image_paths,
        )
        items.append(
            {
                "idx": pp.panel_idx,
                "prompt_text": pp.prompt_text,
                "refs": [str(p) for p in pp.ref_image_paths],
                "ref_sha256": [
                    hashlib.sha256(p.read_bytes()).hexdigest() for p in pp.ref_image_paths
                ],
                "scene_sha256": payload_hash(specs[pp.panel_idx].model_dump()),
                "fingerprint": guard.fingerprint,
            }
        )
    candidate["_reviewed_image_inputs"] = {
        "version": "reviewed-image-inputs-2",
        "script_hash": script_hash(candidate),
        "model": "gemini-2.5-flash-image",
        "aspect_ratio": "4:5",
        "panels": items,
    }
    reviewed_panel_prompts(candidate)
    bundle = {
        "version": "image-quality-candidate-1",
        "purpose": "QUALITY_RETAKE",
        "id": str(uuid.uuid4()),
        "date": candidate["date"],
        "revision": revision,
        "source_script": deepcopy(source),
        "candidate_script": candidate,
        "base_manifest": deepcopy(base_manifest),
        "base_artifact_run_id": base_run_id,
        "base_selection_version": base_selection_version,
        "max_calls": len(panels),
        "max_cost_usd": max_cost_usd,
        "panels": [
            {"panel_idx": item["idx"], "fingerprint": item["fingerprint"]}
            for item in items
            if item["idx"] in panels
        ],
        "storyboard_report": rhythm_report(list(specs.values())),
    }
    return bundle


class QualityGuard(ProductionGenerationGuard):
    def __init__(self, *, candidate_id: str, scope: str, panel: int, prompt: str, refs: list[Path]):
        super().__init__(scope=scope, panel=panel, prompt=prompt, refs=refs)
        self.candidate_id = str(uuid.UUID(candidate_id))

    def reuse(self, output_path: Path) -> bool:
        from engine.image.provider_outcome import outcome_v3_enabled

        if not outcome_v3_enabled():
            raise GenerationHold("Quality retakes require outcome v3")
        receipt = rpc(
            "image_quality_inspect",
            {"p_id": self.candidate_id, "p_panel": self.panel, "p_fingerprint": self.fingerprint},
        )
        digest = receipt.get("output_hash")
        if digest:
            if (
                not output_path.is_file()
                or hashlib.sha256(output_path.read_bytes()).hexdigest() != digest
            ):
                raise GenerationHold("Restore successful quality artifact; do not regenerate")
            return True
        if output_path.exists():
            raise GenerationHold("Unreceipted quality image requires reconciliation")
        return False

    def reserve(self) -> str:
        result = rpc(
            "image_quality_reserve",
            {
                "p_id": self.candidate_id,
                "p_panel": self.panel,
                "p_fingerprint": self.fingerprint,
                "p_run_id": os.environ.get("GITHUB_RUN_ID"),
            },
        )
        if not result.get("token"):
            raise GenerationHold("Missing quality reservation token")
        return result["token"]


def generate(candidate_id: str, output_root: Path) -> dict:
    """One paid attempt per selected panel. A failure never triggers a paid retry."""
    from engine.common.supabase_client import get_client, get_schema
    from engine.image.gemini_client import generate_panel
    from engine.image.reviewed_inputs import reviewed_panel_prompts

    candidate_id = str(uuid.UUID(candidate_id))
    data = (
        get_client()
        .schema(get_schema())
        .table("image_quality_candidates")
        .select("*")
        .eq("id", candidate_id)
        .execute()
        .data
    )
    if len(data) != 1 or data[0]["state"] != "APPROVED":
        raise GenerationHold("Approved quality candidate required")
    bundle = data[0]["bundle"]
    if os.environ.get("ICG_GENERATION_REVISION") != str(bundle["revision"]):
        raise GenerationHold("Quality revision changed")
    script = bundle["candidate_script"]
    from engine.assembly.pil_composer import require_korean_font

    selected = {item["panel_idx"] for item in bundle["panels"]}
    require_korean_font(
        [
            text
            for panel in script["panels"]
            if panel["idx"] in selected
            for text in (
                panel.get("key_text", ""),
                panel.get("narration", ""),
                panel.get("market_ref") or "",
            )
        ]
    )
    prompts = {pp.panel_idx: pp for pp in reviewed_panel_prompts(script)}
    # Validate every selected fingerprint before the first paid call.
    guards = {}
    for item in bundle["panels"]:
        idx = item["panel_idx"]
        pp = prompts[idx]
        g = QualityGuard(
            candidate_id=candidate_id,
            scope=f"output/episodes/{bundle['date']}/panels",
            panel=idx,
            prompt=pp.prompt_text + "\n[model=gemini-2.5-flash-image;aspect=4:5]",
            refs=pp.ref_image_paths,
        )
        if g.fingerprint != item["fingerprint"]:
            raise GenerationHold("Quality fingerprint changed")
        rpc(
            "image_quality_inspect",
            {"p_id": candidate_id, "p_panel": idx, "p_fingerprint": g.fingerprint},
        )
        guards[idx] = g
    root = Path(output_root) / candidate_id
    root.mkdir(parents=True, exist_ok=True)
    result = {"candidate_id": candidate_id, "quality_status": "UNKNOWN", "panels": []}
    for item in bundle["panels"]:
        idx = item["panel_idx"]
        pp = prompts[idx]
        path, cost = generate_panel(
            idx,
            pp.prompt_text,
            pp.ref_image_paths,
            root,
            root / "generation.log",
            aspect_ratio="4:5",
            guard=guards[idx],
        )
        if not path:
            raise GenerationHold("Quality image missing; review before any further call")
        result["panels"].append(
            {
                "panel_idx": idx,
                "output_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                "cost_usd": cost,
                "quality_status": "UNKNOWN",
            }
        )
        from engine.assembly.pil_composer import _compose_image_slide

        preview_dir = root / "previews"
        preview_dir.mkdir(exist_ok=True)
        panel = next(p for p in script["panels"] if p["idx"] == idx)
        _compose_image_slide(
            preview_dir / f"P{idx}-slide.png",
            path,
            panel.get("key_text", ""),
            panel.get("narration", ""),
            idx,
            panel.get("market_ref"),
            strict=True,
        )
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def rebuild_previews(
    script: dict, receipt: dict, artifact_root: Path, output_dir: Path
) -> list[Path]:
    """Recompose successful PNGs offline; never spend again to repair captions.

    The caller must supply the original frozen candidate script and receipt.
    Verify the complete local set before writing any preview.
    """
    from engine.assembly.pil_composer import _compose_image_slide, require_korean_font
    from engine.image.gemini_client import _validate_png

    panels = {p["idx"]: p for p in script["panels"]}
    items = receipt.get("panels")
    if not items or len({p["panel_idx"] for p in items}) != len(items):
        raise GenerationHold("Unique successful image receipt required")
    sources = []
    texts = []
    for item in items:
        idx = item["panel_idx"]
        if type(idx) is not int or idx not in panels:
            raise GenerationHold("Preview panel outside candidate script")
        source = Path(artifact_root) / f"P{idx}.png"
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.get("output_hash"):
            raise GenerationHold("Preview image differs from successful receipt")
        _validate_png(raw)
        panel = panels[idx]
        texts.extend(
            [panel.get("key_text", ""), panel.get("narration", ""), panel.get("market_ref") or ""]
        )
        sources.append((idx, source, panel))
    require_korean_font(texts)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for idx, source, panel in sources:
        output = output_dir / f"P{idx}-slide.png"
        if output.resolve() == source.resolve():
            raise GenerationHold("Preview cannot overwrite source image")
        _compose_image_slide(
            output,
            source,
            panel.get("key_text", ""),
            panel.get("narration", ""),
            idx,
            panel.get("market_ref"),
            strict=True,
        )
        outputs.append(output)
    return outputs


def materialize_selection(
    manifest: list[dict], artifact_root: Path, output_dir: Path
) -> list[Path]:
    """Verified image export, no DB/publication writes. Root is RUN_ID/ARTIFACT_NAME/PATH."""
    import shutil

    from engine.image.gemini_client import _validate_png

    verified = []
    if not manifest or len({m["panel_idx"] for m in manifest}) != len(manifest):
        raise GenerationHold("Unique selected panel manifest required")
    root = artifact_root.resolve()
    for item in manifest:
        run = str(item["artifact_run_id"])
        name = str(item["artifact_name"])
        rel = PurePosixPath(item["artifact_path"])
        if (
            not run.isascii()
            or not run.isdigit()
            or not name.startswith(("episode-", "image-quality-"))
            or "/" in name
            or "\\" in name
            or rel.is_absolute()
            or ".." in rel.parts
            or "\\" in str(rel)
            or type(item["panel_idx"]) is not int
            or item["panel_idx"] < 1
        ):
            raise GenerationHold("Unsafe selected artifact path")
        path = (root / run / name / rel).resolve()
        if (
            not path.is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["output_hash"]
        ):
            raise GenerationHold("Selected image bytes changed")
        _validate_png(path.read_bytes())
        verified.append((item["panel_idx"], path))
    # All inputs verified before writing, never partially overwrite an existing export.
    output_dir.mkdir(parents=True, exist_ok=False)
    paths = []
    for idx, path in verified:
        target = output_dir / f"P{idx}.png"
        shutil.copyfile(path, target)
        paths.append(target)
    return paths


def load_selection(episode_date: str, expected_version: int) -> dict:
    from datetime import date

    from engine.common.supabase_client import get_client, get_schema

    if date.fromisoformat(episode_date).isoformat() != episode_date or expected_version < 1:
        raise GenerationHold("Explicit selected quality version required")
    scope = f"output/episodes/{episode_date}/panels"
    rows = (
        get_client()
        .schema(get_schema())
        .table("image_quality_selections")
        .select("version,manifest")
        .eq("scope", scope)
        .execute()
    ).data
    if len(rows) != 1 or rows[0]["version"] != expected_version:
        raise GenerationHold("Quality selection version changed")
    return {"scope": scope, "version": expected_version, "manifest": rows[0]["manifest"]}


def require_current_selection(marker: dict) -> None:
    episode_date = marker["scope"].split("/")[2]
    if load_selection(episode_date, marker["version"]) != marker:
        raise GenerationHold("Selected quality manifest changed; reassemble before publication")


def selected_sources(
    script: dict, artifact_root: Path, expected_version: int, output_dir: Path
) -> tuple[list[Path | None], dict]:
    marker = load_selection(script["date"], expected_version)
    manifest = marker["manifest"]
    paid = {
        p["idx"] for p in script["panels"] if p["panel_type"] not in {"TEXT_CARD", "DISCLAIMER"}
    }
    if {p["panel_idx"] for p in manifest} != paid:
        raise GenerationHold("Selected quality source coverage changed")
    paths = materialize_selection(manifest, artifact_root, output_dir)
    by_idx = {p["panel_idx"]: path for p, path in zip(manifest, paths)}
    return [by_idx.get(p["idx"]) for p in script["panels"]], marker


def pending_human_gate(episode_date: str) -> bool:
    """Only enabled after the additive DB contract is deployed; fail closed on DB errors."""
    from engine.common.supabase_client import get_client, get_schema

    if os.environ.get("ICG_IMAGE_QUALITY_CANDIDATES_ENABLED", "false").lower() != "true":
        return False
    scope = f"output/episodes/{episode_date}/panels"
    schema = get_client().schema(get_schema())
    pending = (
        schema.table("image_quality_candidates")
        .select("id")
        .eq("scope", scope)
        .in_("state", ["DRAFT", "APPROVED", "REVIEWED"])
        .limit(1)
        .execute()
        .data
    )
    selected = (
        schema.table("image_quality_selections")
        .select("version")
        .eq("scope", scope)
        .limit(1)
        .execute()
        .data
    )
    return bool(pending or selected)


def require_publication_gate(script: dict) -> None:
    from engine.common.supabase_client import get_client, get_schema

    if not pending_human_gate(script.get("date", "")):
        return
    marker = script.get("_image_quality_selection")
    if not marker:
        raise GenerationHold("Quality human gate pending; approved selected assembly required")
    pending = (
        get_client()
        .schema(get_schema())
        .table("image_quality_candidates")
        .select("id")
        .eq("scope", marker["scope"])
        .in_("state", ["DRAFT", "APPROVED", "REVIEWED"])
        .limit(1)
        .execute()
    ).data
    if pending:
        raise GenerationHold("New quality candidate still requires human review")
    require_current_selection(marker)
