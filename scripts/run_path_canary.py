"""Manual canary for a dormant generation path. One paid panel at most; never publishes.

Usage:
  python -m scripts.run_path_canary --path-key ONE_VS_ONE:COMBAT --dry-run
  python -m scripts.run_path_canary --path-key ONE_VS_ONE:COMBAT
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = {"ONE_VS_ONE:COMBAT": Path("config/canary/combat_v1.json")}
REPORT = Path("output/path-canary/report.json")


def build_canary_prompt(path_key: str):
    from engine.image.prompt_builder import build_for_episode

    fixture = json.loads(FIXTURES[path_key].read_text(encoding="utf-8"))
    if fixture.get("path_key") != path_key:
        raise ValueError("canary fixture path mismatch")
    prompts = build_for_episode(fixture["script"], performance_specs=None,
                                battle_outcome=fixture.get("battle_outcome"))
    if len(prompts) != 1 or not prompts[0].prompt_text.strip():
        raise ValueError("canary fixture must compile to exactly one paid panel")
    return prompts[0]


def classify(exc: BaseException | None) -> tuple[str, str | None]:
    if exc is None:
        return "pass", None
    match = re.search(r"provider_reason=([^;]+)", str(exc))
    if match:
        return "refused", match.group(1).strip()
    return "error", type(exc).__name__


def run(path_key: str, *, dry_run: bool) -> dict:
    from engine.image.action_safety import check_action
    from engine.image.generation_guard import ProductionGenerationGuard

    prompt = build_canary_prompt(path_key)
    fixture = json.loads(FIXTURES[path_key].read_text(encoding="utf-8"))
    unsafe = check_action(fixture["script"]["panels"][0].get("action", ""), 1)
    if unsafe:
        raise ValueError("canary fixture violates action safety rules")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    day = datetime.now(timezone.utc).date().isoformat()
    slug = path_key.lower().replace(":", "_")
    scope_dir = Path(f"output/canary/{day}/{slug}/{run_id}")
    fingerprint = ProductionGenerationGuard(
        scope=scope_dir.as_posix(), panel=1,
        prompt=prompt.prompt_text + "\n[model=gemini-2.5-flash-image;aspect=None]",
        refs=prompt.ref_image_paths,
    ).fingerprint
    report = {"path_key": path_key, "dry_run": dry_run, "fingerprint": fingerprint,
              "refs": [str(p) for p in prompt.ref_image_paths], "paid_calls": 0}
    if dry_run:
        report["status"] = "dry_run"
        return report

    from engine.common.supabase_client import icg_table
    from engine.image.gemini_client import generate_panel

    error = None
    cost = None
    try:
        path, cost = generate_panel(1, prompt.prompt_text, prompt.ref_image_paths, scope_dir,
                                    scope_dir / "gemini_run.log")
        if path is None:
            raise RuntimeError("canary produced no image")
    except Exception as exc:  # outcome is recorded, never retried here
        error = exc
    status, reason = classify(error)
    report.update(status=status, finish_reason=reason, cost_usd=cost, paid_calls=1)
    icg_table("path_canary_runs").insert({
        "path_key": path_key, "status": status, "finish_reason": reason,
        "cost": cost, "fingerprint": fingerprint, "run_id": run_id,
    }).execute()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path-key", required=True, choices=sorted(FIXTURES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = run(args.path_key, dry_run=args.dry_run)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {"pass", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
