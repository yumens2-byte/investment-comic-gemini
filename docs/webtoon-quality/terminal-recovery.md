# Reviewed terminal recovery

A terminal provider call remains terminal, with its original token, fingerprint and cost.
Changing `ICG_GENERATION_REVISION` alone cannot release a hold. Reserved and unknown
calls always freeze the scope, including scopes with an earlier recovery receipt.

`docs/sql/image-generation-recovery.sql` is a deployment proposal, not an applied
production migration. Apply it after the existing guard and revision SQL, before
attempting the new recovery RPC. Normal generation without a terminal remains compatible.
The legacy revision-1 guard remains closed for terminal scopes.

## Review and execution

1. Run `python -m scripts.inspect_episode_recovery --date YYYY-MM-DD --output audit.json`.
   This reads the complete ledger and latest published episode. Its proposed hook repair
   contains the expected current-state hash and published-source script hash. It writes
   no database rows and grants no generation permission. If state differs from the last
   published narrative, resolve the evidence and rebuild the candidate before proceeding.
2. Review the replacement scene against the existing canon and content policy. A provider
   refusal does not identify which phrase caused it. Do not repeat a refused input or
   describe a redesign as a moderation bypass. Preserve all images and provider evidence.
3. Persist the reviewed new narrative with a compare-and-swap against the previous script.
   Preserve `CONTENT_QC_HOLD`. Verify the state candidate's base against the corrected state.
   Compile the actual provider prompts, including model/aspect settings and reference
   image bytes. Compute fingerprints using `ProductionGenerationGuard` for every paid scene;
   omit deterministic `TEXT_CARD` and `DISCLAIMER` panels.
4. As service role, call `image_generation_acknowledge_terminal` with the exact terminal
   token, target revision, known actual cost, persisted script JSON, map of scene indices
   to fingerprints, and the reviewed billing/redesign evidence (at least 20 characters).
   Acknowledge every terminal in the scope. The RPC adds a receipt only. It neither changes
   the script nor calls a provider. Repeating the exact request is idempotent; changing an
   existing receipt is rejected. An unsettled call, cost mismatch, missing scene, unchanged
   refused fingerprint or stale script keeps the hold.
5. Only Run Market `--stage image` can use a matching receipt. Narrative/recovery/all stages
   remain blocked, as regenerating narrative invalidates the review. Inspect/reserve verify
   every requested fingerprint against the receipt and retain all original budget totals.
   A new provider refusal freezes the scope again. Receipt authorization does not authorize
   publishing: full content QC and source-hash checks still apply before assembly/delivery.

## Validation

Unit tests cover fail-closed receipts, unavailable RPCs, restricted stages, unsettled calls,
read-only state evidence, and candidate drift. The isolated PostgreSQL CI contract covers
cost/input mismatches, ledger preservation, receipt idempotence, changed scripts/fingerprints,
new failures, original budget caps and restricted role access. The SQL contract refuses
non-local database URLs.
