"""Operator-enabled automatic preparation, model review and approval. No human attestation."""

import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sidestory.market_talk.content import Context, Draft, Evidence, canon, digest, normalize
from sidestory.market_talk.generation import generate, review
from sidestory.market_talk.service import approve, inspect

KST = timezone(timedelta(hours=9))
ACTOR = "market-talk:auto-v1"


def prepare_context(client, canon_path, allowed, now, source_commit):
    day = now.astimezone(KST).date()
    rows = (
        client.schema("icg_side")
        .table("main_feed_market_v1")
        .select("*")
        .lte("snapshot_date", day.isoformat())
        .order("snapshot_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("automatic snapshot unavailable")
    snapshot = rows[0]
    source_day = date.fromisoformat(snapshot["snapshot_date"])
    if not 0 <= (day - source_day).days <= 3:
        raise ValueError("automatic snapshot stale")
    fields = ("vix", "us10y", "oil_wti", "spy_change", "nasdaq_change", "fear_greed")
    for field in fields:
        value = snapshot.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("automatic snapshot incomplete")
    if not (0 <= snapshot["vix"] <= 200 and 0 <= snapshot["fear_greed"] <= 100):
        raise ValueError("automatic snapshot invalid")
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("immutable source commit required")
    characters = sorted(allowed)
    if not characters:
        raise ValueError("automatic character allowlist required")
    fields_canon = canon(canon_path, characters[day.toordinal() % len(characters)], allowed)
    observed = now
    statement = (
        f"저장된 시장 스냅샷({source_day.isoformat()}): "
        + ", ".join(f"{field}={snapshot[field]}" for field in fields)
        + "."
    )
    evidence = Evidence(
        id="STORED_SNAPSHOT",
        statement=statement,
        source_url=f"https://github.com/yumens2-byte/investment-comic-gemini/blob/{source_commit}/sidestory/migrations/0001_icg_side_schema.sql",
        observed_at=observed,
        market_session="DB 조회 시각 · 링크는 읽기 뷰 정의 · 원본 실시간 시세 재검증 아님",
    )
    expires = datetime.combine(day, time(23, 59), KST)
    context = Context(
        policy_version="market-talk-2",
        **fields_canon,
        topic="시장 기록을 보며 나누는 캐릭터 잡담",
        claim_key="auto-snapshot-" + source_day.isoformat(),
        kind="market_close",
        snapshot_date=source_day.isoformat(),
        snapshot_hash=digest(snapshot),
        evidence=[evidence],
        expires_at=expires,
        provenance_reviewer=ACTOR,
        provenance_note="저장된 스냅샷과 카논을 자동 선택. 원본 시세의 외부 검증이나 사람 검수로 표시하지 않음.",
    )
    return context, datetime.combine(day, time(18, 30), KST)


def automatic_draft(
    client,
    store,
    page,
    *,
    canon_path,
    allowed,
    now,
    source_commit,
    model,
    input_rate,
    output_rate,
    current,
):
    day = now.astimezone(KST).date()
    if day.weekday() >= 5:
        return {"status": "SKIPPED_WEEKEND", "allowed": False}
    policy = store.policy(page)
    if not policy["enabled"] or not (
        policy["exclusive_managed"] or policy.get("coexistence_allowed", False)
    ):
        return {"status": "BLOCKED", "blockers": ["PAGE_POLICY_DISABLED"]}
    if not model or any(
        Decimal(str(r)) <= 0 or not Decimal(str(r)).is_finite() for r in (input_rate, output_rate)
    ):
        return {"status": "BLOCKED", "blockers": ["MODEL_AND_RATES_REQUIRED"]}
    if policy["daily_budget_usd"] <= 0 or policy["monthly_budget_usd"] <= 0:
        return {"status": "BLOCKED", "blockers": ["GENERATION_BUDGET_REQUIRED"]}
    start = datetime.combine(day, time.min, KST)
    row = store.daily_auto_item(page, start, start + timedelta(days=1))
    if row:
        draft = Draft.model_validate(row["payload"])
        if row["status"] == "PUBLISHED":
            return {"status": "ALREADY_PUBLISHED", "revision": row["revision"]}
        if row["status"] == "CONTENT_HOLD":
            return {"status": "SKIPPED_CONTENT_HOLD", "revision": row["revision"]}
        if draft.revision != row["revision"] or draft.body != row["body"]:
            raise ValueError("automatic stored revision mismatch")
    else:
        context, due = prepare_context(client, canon_path, allowed, now, source_commit)
        key = digest(
            [
                normalize(context.topic),
                normalize(context.claim_key),
                sorted(e.id for e in context.evidence),
            ]
        )
        if any(r.get("semantic_key") == key for r in store.recent(page)):
            return {"status": "SKIPPED_DUPLICATE_SOURCE", "allowed": False}
        copy = generate(
            context,
            store,
            page,
            model=model,
            input_rate=input_rate,
            output_rate=output_rate,
            request_key=digest(["auto-generate-v1", day.isoformat()]),
        )
        draft = Draft(context=context, text=copy, due_at=due)
        ch, sh = current(client, context)
        report = inspect(draft, store, page, now=now, canon_hash=ch, snapshot_hash=sh)
        if report["errors"]:
            return {"status": "SKIPPED_QUALITY", "errors": report["errors"], "allowed": False}
        store.put(page, draft)
        row = {"status": "DRAFT"}
    ch, sh = current(client, draft.context)
    report = inspect(draft, store, page, now=now, canon_hash=ch, snapshot_hash=sh)
    if report["errors"]:
        return {"status": "SKIPPED_QUALITY", "errors": report["errors"], "allowed": False}
    if row["status"] == "DRAFT":
        verdict = review(
            draft, store, page, model=model, input_rate=input_rate, output_rate=output_rate
        )
        if not verdict.accepted:
            store.rpc(
                "talk_hold",
                p_revision=draft.revision,
                p_actor=ACTOR,
                p_note="자동 모델 검수에서 근거·카논·문장 조건 미충족. 재생성하지 않음.",
            )
            return {"status": "SKIPPED_MODEL_REVIEW", "revision": draft.revision}
        ch, sh = current(client, draft.context)
        approve(
            draft.revision,
            store,
            actor=ACTOR,
            note="자동 결정론 검사 및 독립 모델 검수 통과. 사람 검수 아님. "
            + digest(verdict.model_dump()),
            now=now,
            canon_hash=ch,
            snapshot_hash=sh,
        )
    return {"status": "AUTO_APPROVED", "revision": draft.revision, "reviewer": ACTOR}
