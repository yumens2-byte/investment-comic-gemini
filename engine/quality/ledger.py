"""Durable, atomic single-host pilot ledger.

SQLite is NOT a distributed GitHub Actions coordination mechanism. The pilot
publisher below rejects live use. This backend permits meaningful local race,
restart, partial-success, unknown-result, and budget tests before a production
database adapter is approved and deployed.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from engine.quality.contracts import QualityHold


def money_units(value: str | Decimal) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise QualityHold("cost must be finite and nonnegative")
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


class PilotLedger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, episode TEXT NOT NULL, kind TEXT NOT NULL,
                    panel INTEGER, period TEXT NOT NULL, day TEXT NOT NULL,
                    amount INTEGER NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    key TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
                    token TEXT NOT NULL, state TEXT NOT NULL, external_id TEXT,
                    detail TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(
        self,
        *,
        episode: str,
        kind: str,
        panel: int | None,
        estimate: str,
        episode_cap: str,
        daily_cap: str,
        monthly_cap: str,
        max_calls: int,
        max_panel_calls: int = 2,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or max_calls <= 0 or max_panel_calls <= 0:
            raise QualityHold("invalid reservation limits/time")
        now = now.astimezone(timezone.utc)
        amount = money_units(estimate)
        caps = [money_units(v) for v in (episode_cap, daily_cap, monthly_cap)]
        if any(v <= 0 for v in caps) or amount <= 0:
            raise QualityHold("explicit positive cost caps/estimate required")
        with self.transaction() as db:
            if db.execute(
                "SELECT 1 FROM calls WHERE episode=? AND state IN ('reserved','unknown','over_budget')",
                (episode,),
            ).fetchone():
                raise QualityHold("unsettled provider call requires reconciliation")
            calls = db.execute(
                "SELECT COUNT(*) FROM calls WHERE episode=? AND kind=?", (episode, kind)
            ).fetchone()[0]
            panel_calls = db.execute(
                "SELECT COUNT(*) FROM calls WHERE episode=? AND kind=? AND panel IS ?",
                (episode, kind, panel),
            ).fetchone()[0]
            if calls >= max_calls or (panel is not None and panel_calls >= max_panel_calls):
                raise QualityHold("persistent call limit reached")
            for (column, key), cap in zip(
                (
                    ("episode", episode),
                    ("day", now.date().isoformat()),
                    ("period", now.strftime("%Y-%m")),
                ),
                caps,
            ):
                spent = db.execute(
                    f"SELECT COALESCE(SUM(amount),0) FROM calls WHERE {column}=?", (key,)
                ).fetchone()[0]
                if spent + amount > cap:
                    raise QualityHold(f"{column} cost cap exceeded")
            call_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    call_id,
                    episode,
                    kind,
                    panel,
                    now.strftime("%Y-%m"),
                    now.date().isoformat(),
                    amount,
                    "reserved",
                    now.isoformat(),
                ),
            )
        return call_id

    def settle(self, call_id: str, actual: str | None, *, failed: bool = False) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
            if row is None or row["state"] not in {"reserved", "unknown"}:
                raise QualityHold("call reservation absent or already settled")
            # Never free an ambiguous provider charge. Keep the full reservation
            # when usage is unavailable, including timeouts and process crashes.
            amount = row["amount"] if actual is None else money_units(actual)
            overrun = actual is not None and amount > row["amount"]
            state = (
                "unknown"
                if actual is None
                else ("over_budget" if overrun else ("failed" if failed else "settled"))
            )
            db.execute("UPDATE calls SET amount=?,state=? WHERE id=?", (amount, state, call_id))

        if overrun:
            self.event(
                "cost_overrun", {"call_id": call_id, "reserved": row["amount"], "actual": amount}
            )
            raise QualityHold("actual provider charge exceeds reserved maximum; episode held")

    def claim(self, key: str, content_hash: str) -> tuple[str | None, str | None]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row:
                if row["content_hash"] != content_hash:
                    raise QualityHold("publication key reused for different content")
                if row["state"] == "published":
                    return None, row["external_id"]
                if row["state"] != "failed":
                    raise QualityHold(f"publication requires reconciliation: {row['state']}")
            token = str(uuid.uuid4())
            db.execute(
                """INSERT INTO jobs(key,content_hash,token,state,updated_at)
                       VALUES (?,?,?,'sending',?) ON CONFLICT(key) DO UPDATE SET
                       token=excluded.token,state='sending',updated_at=excluded.updated_at""",
                (key, content_hash, token, datetime.now(timezone.utc).isoformat()),
            )
            return token, None

    def finish(
        self, key: str, token: str, state: str, external_id: str | None = None, detail: str = ""
    ) -> None:
        if state not in {"published", "failed", "unknown"}:
            raise QualityHold("invalid publication result")
        if state == "published" and not external_id:
            raise QualityHold("published requires external ID")
        with self.transaction() as db:
            updated = db.execute(
                """UPDATE jobs SET state=?,external_id=?,detail=?,updated_at=?
                                   WHERE key=? AND token=? AND state='sending'""",
                (state, external_id, detail, datetime.now(timezone.utc).isoformat(), key, token),
            ).rowcount
            if updated != 1:
                raise QualityHold("stale fencing token or completed job")

    def reconcile(
        self,
        key: str,
        *,
        external_id: str | None,
        reviewer: str,
        proof: str,
        confirmed_absent: bool = False,
    ) -> None:
        if not reviewer.strip() or not proof.strip() or bool(external_id) == confirmed_absent:
            raise QualityHold("reconciliation needs evidence of posted OR confirmed absent")
        with self.transaction() as db:
            row = db.execute("SELECT state FROM jobs WHERE key=?", (key,)).fetchone()
            if row is None or row["state"] not in {"sending", "unknown"}:
                raise QualityHold("not an ambiguous publication")
            db.execute(
                "UPDATE jobs SET state=?,external_id=?,token=?,detail=? WHERE key=?",
                (
                    "published" if external_id else "failed",
                    external_id,
                    str(uuid.uuid4()),
                    json.dumps({"reviewer": reviewer, "proof": proof}),
                    key,
                ),
            )

    def event(self, kind: str, payload: dict) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    kind,
                    json.dumps(payload, allow_nan=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def snapshot(self) -> dict:
        with self.transaction() as db:
            return {
                t: [dict(r) for r in db.execute(f"SELECT * FROM {t}")]
                for t in ("calls", "jobs", "events")
            }

    def unsettled_calls(self, episode: str) -> list[str]:
        with self.transaction() as db:
            return [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM calls WHERE episode=? "
                    "AND state IN ('reserved','unknown','over_budget')",
                    (episode,),
                )
            ]
