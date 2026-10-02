# Pipeline normalization after partial rollback

## Problem and restored behavior

Main `d9b7d263ea994114802a1447f985e968d5dc4dbf` mixed older Python files
with the newer workflows, database adapters, and tests. CI failed during
collection because `_validate_slides` had been removed; Publish SNS rejected
the workflow's `--preflight-only` argument. Similar regressions removed durable
image generation reservations, strict source-image assembly, artifact manifests,
and delivery-confirmed story-state commits.

This change restores all 35 divergent files to the compatible implementation
at `72ae2ea7d2194668879584c18cc85d4ce42bc270` (PR #88). It preserves current
Git history and existing database adapters. That candidate passed 1,346 tests
but is not evidence of a corrected episode or successful live publication.

| Pipeline | Restored behavior | Regression coverage |
|---|---|---|
| Data and analysis | Read-only preflight before writes; exact episode identity | market quality, analysis helpers, market dry-run suites |
| Narrative and arc | Evidence-backed thread transitions, zero-valued tension, episode dates, observation without forced victory | narrative repair, continuity, story state, arc idempotency |
| Image generation | Durable reservations, cumulative revision budgets, verified image reuse, billing uncertainty holds | generation guard, image adapter, image recovery suites |
| Assembly | Restore nested artifacts; reject missing/corrupt sources; bind script and slides with a manifest | composer, assembly artifact, manifest/quality regressions |
| X and Telegram | Read-only readiness; exact identity; reject text fallbacks; store delivery receipts; atomic story commit | publish dry-run, claim, delivery, media suites |
| Video and Shorts | Restore media validation and audited/budgeted retries | shorts pipeline, weekly pipeline/media, video artifact linkage |
| Deployment | Restore CLI options and workflow tests; verify actual supported options and stages | deployment CLI contracts, all-workflow YAML validation |

## Prevention

`test_deployment_cli_contract.py` reads commands from all deployed workflows and
compares their options and literal stage names with the real CLI `--help` output.
It also verifies that every referenced module exists. Help checks use an
environment without provider/database credentials and never execute stages.

Unit CI no longer receives production secrets and defaults to `DRY_RUN=true`.
Tests that exercise delivery and generation use mocks. The isolated PostgreSQL
contract CI still checks receipts, rollback, idempotence, and cumulative revision
budgets. Read-only operational beta workflows retain their separate credentials.

## Validation and operational limits

After restoring the implementation, the existing local Python 3.12 regression
suite passed all 1,346 tests. The 12 new deployment contract tests also passed.
The final combined suite, Ruff, diff checks, Python 3.11 PR CI, and isolated
PostgreSQL CI must pass before deployment.

This development change does not mutate production rows, reset billing ledgers,
reconcile terminal provider results, create paid images, or send SNS posts.
Deployment and episode-data recovery are separate steps. A terminal/unknown
generation record remains a hold until reconciled; changing revision cannot
bypass it. Existing successful images must be located and hash-verified before
deciding whether any additional generation is needed.

Before production rollout:

1. Verify main has not moved since the recovery branch was created.
2. Verify the deployed database and live prompt contracts match the restored code.
3. Inventory the chosen episode's narrative, revision, source artifacts and
   delivery receipts; retain the paid-call ledger and audit history.
4. Reconcile generation holds, restore successful files and QC the exact narrative.
5. Assemble with strict source validation, verify the manifest, and run read-only
   publication readiness with an explicit episode ID.
6. Check existing external posts before selecting a first or corrective publication.

Source restoration alone does not establish full production recovery. CI success,
episode-content QC, and confirmed live delivery must be reported separately.
