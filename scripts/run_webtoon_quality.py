"""Validate offline webtoon quality inputs or an exact reviewed release.

No network calls, DB mutations, paid generation or live publication are available.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.quality.canon import CanonManifest
from engine.quality.contracts import Claim, EditorialPlan, EvidenceBundle, QualityHold
from engine.quality.pipeline import prepare
from engine.quality.release import QualityReport, ReleaseManifest


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--contract", type=Path, required=True)
    prep.add_argument("--root", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    for name in ("manifest", "inputs", "report", "root"):
        verify.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            document = read_json(args.contract)
            prepared = prepare(
                bundle=EvidenceBundle.model_validate(document["evidence"]),
                plan=EditorialPlan.model_validate(document["editorial"]),
                claims=[Claim.model_validate(c) for c in document["claims"]],
                canon=CanonManifest.model_validate(document["canon"]),
                script=document["script"],
                calculation=document["calculation"],
                root=args.root,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("Prepared: awaiting_images_and_human_review")
        else:
            manifest = ReleaseManifest.model_validate(read_json(args.manifest))
            manifest.verify(
                args.root,
                read_json(args.inputs),
                QualityReport.model_validate(read_json(args.report)),
            )
            print("Exact reviewed release verified (offline; no publication)")
    except (QualityHold, ValueError, KeyError, OSError) as exc:
        print(f"HOLD: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
