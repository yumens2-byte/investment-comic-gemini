"""Recovery check must never unlock HOLD, purchase images, or post to Facebook."""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from sidestory.app.recovery_preflight import check_recovery
from sidestory.tests.fixtures import FakeStore

DAY = date(2026, 10, 15)
SID = "SIDE-2026-10-15-01"


def _seed(store: FakeStore, *, status: str = "hold", panels: dict | None = None) -> None:
    store.upsert_episode(SID, {
        "status": status,
        "error_message": "image: P1 provider outcome requires reconciliation",
        "script_json": {"existing": True},
        "panels_json": panels,
    })


def _scope(root: Path, *, retake: bool = False) -> str:
    return (root / DAY.isoformat() / ("v2/panels" if retake else "panels")).as_posix()


def test_503_unknown_is_blocked_instead_of_paid_retry(tmp_path: Path) -> None:
    store = FakeStore()
    root = tmp_path / "output" / "sidestory"
    _seed(store)
    store.ledger_blockers.append({"scope": _scope(root), "panel": 1,
                                  "state": "unknown", "created_at": "2026-10-15T05:55:48Z"})
    original = dict(store.get_episode(SID))
    result = check_recovery(DAY, store, output_root=root)

    assert result["status"] == "BLOCKED_LEDGER_RECONCILIATION"
    assert result["read_only"] and not result["may_retry_paid"] and not result["may_publish"]
    assert result["ledger_blockers"][0]["panel"] == 1
    assert result["ledger_blockers"][0]["state"] == "unknown"
    assert result["has_script"] is True
    assert store.get_episode(SID) == original
    assert store.logs == []
    assert store.publications if hasattr(store, "publications") else True


def test_both_original_and_retake_scopes_are_checked(tmp_path: Path) -> None:
    store, root = FakeStore(), tmp_path / "output" / "sidestory"
    _seed(store)
    store.ledger_blockers.extend([
        {"scope": _scope(root), "panel": 2, "state": "reserved"},
        {"scope": _scope(root, retake=True), "panel": 2, "state": "terminal"},
    ])
    report = check_recovery(DAY, store, output_root=root)
    assert report["status"] == "BLOCKED_LEDGER_RECONCILIATION"
    assert {x["state"] for x in report["ledger_blockers"]} == {"reserved", "terminal"}


def test_partial_checkpoint_missing_file_fails_closed(tmp_path: Path) -> None:
    store, root = FakeStore(), tmp_path / "output" / "sidestory"
    valid = tmp_path / "P1.png"
    valid.write_bytes(b"immutable saved panel")
    _seed(store, panels={"run_id": "38689330263", "panels": [
        {"idx": 1, "path": str(valid), "sha256": hashlib.sha256(valid.read_bytes()).hexdigest()},
        {"idx": 2, "path": str(tmp_path / "P2.png"), "sha256": "b" * 64},
    ]})
    report = check_recovery(DAY, store, output_root=root)
    assert report["status"] == "BLOCKED_ARTIFACT_RESTORATION"
    assert report["verified_checkpoint_panels"] == [1]
    assert report["invalid_checkpoint_panels"] == [2]
    assert report["checkpoint_run_id"] == "38689330263"


def test_no_blockers_still_requires_operator_review(tmp_path: Path) -> None:
    store = FakeStore()
    _seed(store)
    report = check_recovery(DAY, store, output_root=tmp_path)
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert report["may_retry_paid"] is False


def test_publication_receipt_prevents_second_post(tmp_path: Path) -> None:
    store = FakeStore()
    _seed(store, status="published")
    store.insert_publication({"side_episode_id": SID, "channel": "facebook",
                              "dry_run": False, "post_id": "123456"})
    report = check_recovery(DAY, store, output_root=tmp_path)
    assert report["status"] == "ALREADY_PUBLISHED"
    assert report["has_live_publication"] is True
    assert not report["may_publish"]


def test_missing_episode_has_no_implicit_echo(tmp_path: Path) -> None:
    store = FakeStore()
    report = check_recovery(DAY, store, output_root=tmp_path)
    assert report["status"] == "NO_EPISODE"
    assert store.episodes == {} and store.logs == []
