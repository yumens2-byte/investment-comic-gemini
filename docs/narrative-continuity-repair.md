# Narrative continuity repair — development and rollout

The October 2 episode copied an unanswered question into `resolved_threads` and
received a 100-point continuity score. Both initial prompt construction and retry
feedback required that copy. This change removes those requirements and refuses
unreviewed resolution declarations. Lexical acknowledgement has its own metric;
it is not awarded resolution points.

## Implemented contracts

- Thread transitions retain the previous thread ID and distinguish OPEN,
  PROGRESSED and RESOLVED. Progress requires an actual panel quote and new fact.
  RESOLVED additionally requires an independent review bound to the exact script
  fingerprint. A generated script cannot approve itself. Without a review,
  unanswered threads remain OPEN/PROGRESSED. The current workflow does not create
  an independent semantic review automatically.
- Production validation, persistence and live publication all check the thread
  contract. Mandatory contract errors cannot be overcome by a high score.
- Noncombat episodes use OBSERVATION; they do not imply market growth or increment
  victory counters. Ending tone follows risk. Zero-valued tension/momentum is
  preserved. State updates use the selected episode date.
- Long arcs no longer default every Day 7+ episode to FLASHBACK.
- Persist stores `_state_candidate` without advancing the confirmed arc/story.
  Continuity reads published episodes. Newest thread states take precedence over
  older closed states. Approved resolutions remain in the structured ledger.
- Resume saves an assembly manifest of the narrative and exact slide hashes.
  Changed dialogue or swapped images require reassembly before live publication.
- For candidate-based releases, a read-only database preflight must succeed before
  any send. Each completed X post and Telegram album records its external IDs
  under the publication claim. Final state/history/episode confirmation is one DB
  transaction. Any ambiguous send or failed receipt/state save retains HOLD.
- Explicit image revision uses the same stable date/panel budget. Matching
  prompt/reference fingerprints reuse originals; changed panels require the
  proposed v2 adapter. Only receipted originals may move to previous-revisions.
  Unknown files, ambiguous costs and exhausted budgets still stop generation.
- Optional source artifact restoration copies only the selected date's PNGs,
  never the archived narrative.
- TEXT_CARD image prompts require a neutral background without chart direction,
  tickers or numbers. Text facts remain in the compositor.

## Rollout gates

This development change does not apply SQL or update live Notion prompts.
`docs/sql/narrative-publication-state.sql` and
`docs/sql/image-generation-revision.sql` are deployment proposals, not registered
migrations. Register them with the Supabase CLI migration workflow, review actual
schema compatibility, and run the isolated PostgreSQL contract job before any
production rollout. The functions are SECURITY INVOKER, granted to service_role
only. Existing data/cost ledgers are retained.

The state adapter must be available before candidate-based publication can send.
If it is missing, preflight fails closed. Generation revision 1 retains the
existing fingerprint protection. An operator-selected revision 2+ is authorized
only by the current narrative's recorded revision, and keeps panel/episode/global
budget totals across revisions.

Synchronize the connected Notion system/user templates with schema v2 during
deployment. Runtime adds the authoritative transition contract and removes the
known obsolete fixed-growth line. Character canon/reference rules are unchanged.

For the October 2 recovery, do not run Publish alone. First deploy and verify the
code and DB adapter, verify prior confirmed narrative state, prepare the corrected
narrative, restore originals using source_artifact_run_id=36919762103, explicitly
select generation_revision=2, review affected images, Resume with strict assembly,
and run publication dry preflight. Existing SNS posts remain external objects;
their correction/deletion policy must be handled separately from DB reset.

## Verification

The actual failed episode is retained as a small, non-secret test fixture.
Regressions cover false resolution, independent-review fingerprint binding,
unknown IDs/panels/quotes, honest progress, latest-state precedence, 0 values,
noncombat counters, selected dates, pure candidate generation, manifest tampering,
unavailable DB adapters, verified-original archival and date-only artifact restore.

The PostgreSQL CI job uses a disposable localhost PostgreSQL 16 service and no
production credentials. It compiles the SQL, checks revision reuse and budget
preservation, blocks changed base state and receipt mismatch, verifies rollback,
then confirms state/history exactly once. The test script refuses remote URLs.

Historical 61-win/63-day state was restored, not declared canonically correct.
Reconstruct and review historical published episodes before adjusting that legacy
state; this patch does not erase previous episodes or reset paid-call counters.
