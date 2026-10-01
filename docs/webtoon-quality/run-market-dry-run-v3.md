# Run Market dry-run correction

Incident: Run Market workflow 36871839518 (2026-10-01 22:52 KST) was intended as a dry run. Logs confirmed DRY_RUN=false because the workflow hardcoded false and did not expose a dry_run input. STEP 4 reached the already-published ICG-2026-10-01-001 guard and exited. The data/analysis split workflow had already run before that guard.

The new boolean dry_run dispatch input maps explicitly to string true/false. CLI --dry-run or DRY_RUN=true enters a read-only path before StepLogger, collection, analysis, Claude/Gemini, persistence, Notion mirror or state updates. It reads episode identity/status and cached snapshot/analysis/narrative metadata, emits a local JSON report, and lists new collection/narrative/images/delivery as unverified. It does not simulate generation success. Missing caches are reported as incomplete readiness. Database outages/malformed responses and noncanonical dates fail closed.

Every workflow live stage now requires a preceding successful eligibility preflight. Published/assembled/image_generated episodes, unresolved publication holds and image reserved/unknown/terminal scopes are reported as blocked and skipped before any stage changes. A blocked preflight is a safe no-op, not a failed generation. Database lookup failures remain errors. FORCE_RUN cannot bypass those guards. Direct CLI live entry retains its existing protection.

Dry runs skip the direct Telegram failure notifier and generation-complete summary. Independent Watchdog infrastructure can still alert on a failed workflow; publishes=0 refers to comic publication, not a promise to disable separate health monitoring.

Operator: select Run Market workflow_dispatch dry_run=true to inspect an existing published date. With dry_run=false, an already completed date is blocked; recover previous artifacts or reconcile holds instead of forcing regeneration. The corrected input takes effect on the main version; re-running the old run keeps its original workflow/SHA and does not apply the correction.

Three independent reviewers checked stage isolation, workflow gates and tests. They found and fixed split-stage early writes, compact date acceptance, wrong completion summary and preflight omission of image ledger holds. A separate operational beta runs all/narrative/image readonly against a published episode, checks live preflight blocks, and compares episode/snapshot/analysis/run-log hashes before/after. Only Supabase credentials are supplied; no paid provider or publication credentials are supplied.
