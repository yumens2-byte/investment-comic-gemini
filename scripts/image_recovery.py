"""Stable CLI for common reviewed image recovery; default operation is read-only."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.recovery_service import RecoveryProgressHold, operate, resolve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["inspect", "prepare", "execute"], default="inspect")
    parser.add_argument("--date", default="")
    parser.add_argument("--request", default="")
    parser.add_argument("--request-sha256", default="")
    parser.add_argument("--candidate-sha256", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("output/image-recovery-report.json"))
    parser.add_argument("--resolve-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.resolve_only:
            identity = resolve(args.mode, args.date, args.request, args.request_sha256)
            if os.environ.get("GITHUB_OUTPUT"):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    for key, value in identity.items():
                        stream.write(f"{key}={value}\n")
            print(json.dumps(identity))
            return
        report = operate(args.mode, day=args.date, request_path=args.request,
                         request_sha256=args.request_sha256,
                         candidate_sha256=args.candidate_sha256, confirm=args.confirm,
                         private_dir=args.private_dir)
    except Exception as exc:
        code = str(exc) if isinstance(exc, GenerationHold) else type(exc).__name__
        # Provider/DB exceptions can contain private request text.
        report = dict(exc.report) if isinstance(exc, RecoveryProgressHold) else {"mode": args.mode}
        report.update(status="blocked", error_type=type(exc).__name__,
                      code=code if re.fullmatch(r"[A-Z0-9_]+", code) else "RECOVERY_HELD")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        raise SystemExit(1) from None
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
