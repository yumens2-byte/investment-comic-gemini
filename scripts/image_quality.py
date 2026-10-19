"""Explicit quality candidate gates. Preparation is offline; live actions are opt-in."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.quality_candidates import generate, materialize_selection, prepare, rpc


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=[
            "prepare",
            "register",
            "approve",
            "cancel",
            "generate",
            "review",
            "select",
            "rollback",
            "export",
        ],
    )
    p.add_argument("--source", type=Path)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--review", type=Path)
    p.add_argument("--panels", default="3,5,6")
    p.add_argument("--base-run-id")
    p.add_argument("--revision", type=int)
    p.add_argument("--expected-version", type=int, default=0)
    p.add_argument("--target-version", type=int)
    p.add_argument("--budget", type=float, default=0.30)
    p.add_argument("--id")
    p.add_argument("--digest")
    p.add_argument("--actor")
    p.add_argument("--note")
    p.add_argument("--scope")
    p.add_argument("--artifact-root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    if args.action not in {"prepare", "export"} and (
        not args.live or os.environ.get("DRY_RUN", "true").lower() != "false"
    ):
        p.error("Database and paid actions require --live and DRY_RUN=false")
    if args.action == "prepare":
        result = prepare(
            read(args.source),
            read(args.candidate),
            read(args.manifest),
            revision=args.revision,
            panels=[int(x) for x in args.panels.split(",")],
            base_run_id=args.base_run_id,
            base_selection_version=args.expected_version,
            max_cost_usd=args.budget,
        )
    elif args.action == "export":
        paths = materialize_selection(read(args.manifest), args.artifact_root, args.output)
        print(json.dumps({"exported": len(paths), "publication_authorized": False}))
        return
    elif args.action == "register":
        result = rpc("image_quality_register", {"p_bundle": read(args.bundle)})
    elif args.action == "generate":
        result = generate(args.id, args.output.parent / "images")
    elif args.action in {"approve", "select", "cancel"}:
        params = {
            "p_id": args.id,
            "p_digest": args.digest,
            "p_actor": args.actor,
            "p_note": args.note,
        }
        if args.action == "select":
            params["p_expected_version"] = args.expected_version
        result = rpc("image_quality_" + args.action, params)
    elif args.action == "review":
        result = rpc(
            "image_quality_review",
            {
                "p_id": args.id,
                "p_digest": args.digest,
                "p_actor": args.actor,
                "p_review": read(args.review),
            },
        )
    else:
        result = rpc(
            "image_quality_rollback",
            {
                "p_scope": args.scope,
                "p_expected_version": args.expected_version,
                "p_target_version": args.target_version,
                "p_actor": args.actor,
                "p_note": args.note,
            },
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        args.output.chmod(0o600)
        json.dump(result, f, ensure_ascii=False, indent=2)
    # Prompts, canon and source script must not appear in public logs/artifacts.
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                in {
                    "id",
                    "digest",
                    "registered",
                    "approved",
                    "reviewed",
                    "selected",
                    "rolled_back",
                    "cancelled",
                    "version",
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except GenerationHold as exc:
        raise SystemExit(str(exc)) from exc
