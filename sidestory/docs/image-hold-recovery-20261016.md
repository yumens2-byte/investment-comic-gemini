# Sidestory image HOLD incident and recovery (2026-10-16)

## Evidence (read-only observations)
- GitHub Actions #38689330263 (2026-10-15 slot) exited at the first `image` panel.
- `SIDE-2026-10-15-01` is `hold`; narrative completed, slides/publish did not run.
- `icg_side.image_generation_calls`: scope `output/sidestory/2026-10-15/panels`, panel=1, state=`unknown`, output_hash=null, cost=0.10 (reservation/ledger field; **not verified actual billing**).
- No successful panel receipt; don't claim the upstream request was unbilled or definitively failed.

## Operator procedure: never skip reconciliation
1. Read `icg_side.side_episodes` and `icg_side.image_generation_calls` without modifying rows.
2. Confirm **all** scopes for the date (`panels` and `v2/panels`) have no `reserved`, `unknown`, or `terminal` calls. These states block generation and HOLD release.
3. Reconcile outcome and invoice with provider evidence. An unknown call is not a settled failed call.
4. Apply an explicitly reviewed DB recovery procedure only after evidence and cost are established. Never delete/relabel the call to force another generation.
5. For a resumed P1/auto job, pass the previous GitHub run ID in `artifact_run_id`, use the original date and `retry_hold`. For actual Facebook publishing, ensure explicit live authorization and check for existing posts.
6. Run in dry-run mode first where applicable; verify `side_run_logs`, per-panel SHA-256 / SG-8, `panels_json`, and published state.
7. Do not reset `SIDE-2026-10-15-01` until step 3 is complete.

## Code behavior after this change
- Panel image success is checkpointed individually in `panels_json` only after hash validation and SG-8. While incomplete the episode stays `narrative_done`, or `hold` on failure.
- A resumed image stage checks checkpoint hashes; missing files block paid regeneration until the correct Actions artifact is restored.
- Unsettled original/retake ledger entries stop image generation and prevent `--retry-hold` from releasing an image HOLD.
- Provider exceptions retain a sanitized class name even when ledger settlement raises a separate HOLD; raw exception messages are not included in user-visible status.

## Acceptance
- Offline unit regressions pass, workflow YAML checks pass, current main/side publication paths remain isolated.
- No automatic paid retry on `unknown`; no post without both Facebook live authorization locks.
- No production rollout before green CI and review; the historical incident is a separate reconciliation task.
