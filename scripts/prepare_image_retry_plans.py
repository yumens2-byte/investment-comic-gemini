"""Prepare reviewed repair plans privately; registration is an explicit separate action."""
import argparse
import json
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.repair_plan import prepare, register


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base-prompts", type=Path, required=True)
    parser.add_argument("--repairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.register and args.confirm != "REGISTER_REVIEWED_REPAIR_PLANS":
        parser.error("Registration requires explicit REGISTER_REVIEWED_REPAIR_PLANS confirmation")
    output = args.output.resolve()
    public = Path("output").resolve()
    if output == public or public in output.parents:
        raise GenerationHold("Repair plans must remain outside public artifacts")
    source = json.loads(args.source.read_text())
    candidate, fingerprints = prepare(source, json.loads(args.base_prompts.read_text()),
                                      json.loads(args.repairs.read_text()))
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with output.open("x", encoding="utf-8") as stream:
        output.chmod(0o600)
        json.dump({"source": source, "candidate": candidate, "fingerprints": fingerprints},
                  stream, ensure_ascii=False, indent=2)
    if args.register:
        register(source, candidate, fingerprints)
    print(json.dumps({"prepared": True, "registered": args.register,
                      "paid_calls": 0, "panels": len(fingerprints)}))


if __name__ == "__main__":
    main()
