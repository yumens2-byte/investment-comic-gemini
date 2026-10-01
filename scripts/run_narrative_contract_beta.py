"""Read-only production adapter and live Notion contract verification."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment


def database_fingerprint(table, target: str) -> str:
    payload = {}
    for name, column in (("episode_assets", "episode_date"),
                         ("daily_analysis", "analysis_date"),
                         ("published_comics", "publish_date")):
        payload[name] = table(name).select("*").eq(column, target).execute().data
    payload["arc_state"] = table("arc_state").select("*").eq("id", 1).execute().data
    payload["image_generation_calls"] = table("image_generation_calls").select("*").eq(
        "scope", f"output/episodes/{target}/panels"
    ).execute().data
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    from engine.common.notion_loader import (
        load_narrative_system,
        load_narrative_user_template,
    )
    from engine.common.supabase_client import get_client, get_schema, icg_table
    from scripts.run_operational_beta import inspect_production

    target = os.environ.get("TARGET_DATE") or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    report = {"status": "failed", "target_date": target, "checks": [],
              "database_writes": 0, "paid_calls": 0, "publishes": 0,
              "unverified": ["new_episode_semantic_qc", "live_delivery", "positive_state_commit"]}
    try:
        before = database_fingerprint(icg_table, target)
        metadata = inspect_production(icg_table, dict(os.environ))
        assert metadata["status"] == "pass", "production metadata unavailable or HOLD"
        report["checks"].append("production_metadata_and_configuration")
        api = get_client().schema(get_schema())
        result = api.rpc("publication_state_preflight", {
            "p_date": "1900-01-01", "p_no": 1, "p_candidate": {},
        }).execute().data
        assert result == {"ready": False}, "invalid candidate accepted"
        report["checks"].append("live_state_preflight_rejects_invalid_candidate")
        identity = {"p_scope": f"output/episodes/{target}/panels", "p_panel": 1,
                    "p_fingerprint": "0" * 64, "p_revision": 101}
        result = api.rpc("image_generation_inspect_v2", identity).execute().data
        assert result == {"hold": "invalid identity"}, "invalid revision accepted"
        report["checks"].append("live_revision_inspection_rejects_invalid_identity")
        ledger = icg_table("image_generation_calls").select("revision,cost,state").eq(
            "scope", identity["p_scope"]
        ).execute().data
        assert isinstance(ledger, list) and all(isinstance(r["revision"], int) for r in ledger)
        report["checks"].append("live_paid_ledger_revision_column")
        system = load_narrative_system()
        template = load_narrative_user_template()
        assert "Continuity contract v2" in system and "thread_transitions" in system
        assert "PEACEFUL_GROWTH** — THIS IS FIXED" not in template
        assert "show positive outlook" not in template
        Environment().parse(template)
        report["checks"].append("live_notion_contract_v2_and_jinja_syntax")
        after = database_fingerprint(icg_table, target)
        assert before == after, "production state changed during beta"
        report["checks"].append("episode_analysis_history_arc_paid_ledger_unchanged")
        report["status"] = "pass"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    root = Path("output/narrative-contract-beta")
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
