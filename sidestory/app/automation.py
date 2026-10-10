"""End-to-end side track, preserving existing production and publication gates."""
from datetime import date

from sidestory.app.p1 import P1Deps, StageResult, run_p1
from sidestory.app.pipeline import side_episode_id
from sidestory.app.publish import PublishDeps, run_publish, run_verify


def run_auto(side_day: date, production: P1Deps, publication: PublishDeps, *,
             force: bool = False, retry_hold: bool = False) -> list[StageResult]:
    if production.store is not publication.store or production.feed is not publication.feed:
        raise ValueError("auto requires the same feed and store for all stages")
    sid = side_episode_id(side_day)
    row = production.store.get_episode(sid) or {}
    results = []
    publish_hold = (row.get("error_message") or "").startswith("publish:")
    if row.get("status") not in {"assembled", "publishing", "published"} and not (
            row.get("status") == "hold" and publish_hold):
        results = run_p1(side_day, production, force=force, retry_hold=retry_hold)
        if not results or any(not r.ok or r.status == "skipped" for r in results):
            return results
    published = run_publish(side_day, publication, retry_hold=retry_hold)
    results.append(published)
    if not published.ok:
        return results
    # A dry run can be validated without a Facebook connection.
    if publication.live or publication.publisher is not None:
        results.append(run_verify(side_day, publication))
    return results
