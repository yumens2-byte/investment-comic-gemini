# ICG Gemini / Resume incident review — 2026-10-02

Baseline: main `05f9c28798e5e7c6f86593291acaad13230a3f08` (PR #96).

## Evidence and diagnosis

- Run Market #36994904577 (19:20–19:24 KST) completed ingest, analysis,
  narrative and persistence, then failed on panel 1 image generation.
- Downloaded artifact #11221148592 contains the script, run.log and
  panels/gemini_run.log, with no generated PNG. Provider HTTP 200 does not
  establish image success: the recorded finish reason is
  `FinishReason.PROHIBITED_CONTENT`. Measured recorded cost is USD 0.0007725.
- Read-only production queries confirmed one panel-1/revision-1 `terminal`
  receipt at that cost, zero reserved/unknown calls in the date scope, and
  episode 001 remains `narrative_done`, revision 1. No current content QC
  marker/error is stored; artifact_run_id is null. These are current facts,
  not a claim about the earlier state before today's reset.
- Resume #36975694115, #36993757414 and #36994133690 stopped at the content
  QC gate before assembly. Their tracebacks identify the row's
  CONTENT_QC_HOLD branch. The historical specific reason was hidden by
  the generic exception; current null error cannot prove the old review passed.
- Main CI #36993290611 and operational guard/read-only betas succeeded.
  That does not certify a subsequent character image request or content QC.

## QC execution policy

Content QC defaults to `ICG_QC_MODE=warning`. Failed or stale content review,
reviewed image hashes, narrative continuity/grounding, thread transitions,
production quality, claim evidence, editorial checks, character/cast/performance
checks, mobile text layout, release review scores and video visual/motion/duration
checks emit `[QC_WARNING]` and continue with available valid inputs. X disclaimer
QC also warns. Existing PASS/FAIL/HOLD evidence and measured scores are preserved;
this policy does not fabricate approval or rewrite failed findings as PASS.

The global policy takes precedence over legacy continuity/serial/performance
strict flags. QC-only narrative retries and frozen-video regeneration do not
consume extra paid calls in warning mode. `ICG_QC_MODE=strict` is an explicit
rollback option, exercised by existing regression tests. New tests separately
verify the production warning default with the variable absent.

Actual operational prerequisites remain exceptions: valid structured inputs and
identities, usable files, required reference files and approved source hashes,
API/DB availability, ledger reconciliation/budget limits, provider rejection,
publication claims, durable delivery receipts and duplicate-send protection.
These checks cannot produce a missing image or verify an ambiguous paid call.
Source QC hashes are advisory; immutable generation and publication identity
contracts remain enforced.

## Telegram behavior

Existing failure notifications and normal Telegram publication remain in place.
Six operational workflows add an `always()` QC summary notification with
`continue-on-error: true`, using the same bot and free channel secrets. The
summary includes unique warnings for the current Actions run, bounded and HTML
escaped. Successful jobs can now send QC alerts because warnings no longer
trigger `failure()`. Live preflight QC findings are included even when a later
readiness issue prevents publication. Dry/read-only inspections send no alerts;
Telegram notification failure cannot fail the workflow. Logs retain the findings
if the notification configuration is absent.

## Provider diagnosis

Gemini refusal diagnostics preserve finish reason, panel, measured/unknown cost,
ledger HOLD cause and evidence path. Safe usage fields are logged before the
settlement RPC; prompts, image bytes and credentials are excluded. Terminal and
missing-usage outcomes still have one paid attempt and preserve their exception
chain. No request is retried to bypass provider controls.

## Validation and delivery

Local validation: 1,492 tests passed in 42.84 seconds; Ruff and whitespace
checks passed. The final notification-size adjustment passed all 22 advisory
policy tests. Remote CI conclusions are recorded on PR #97. Tests cover continued assembly with a real
source image and failed review, unchanged failed QC evidence, performance/video
warnings, paid-call/publication safeguards, read-only preflight, dry-run behavior,
Telegram deduplication, current-run filtering and workflow notification steps.

Repository: `yumens2-byte/investment-comic-gemini`.
Branch: `codex/gemini-failure-diagnostics-20261002`.
PR: https://github.com/yumens2-byte/investment-comic-gemini/pull/97.
Main merge/deployment and paid episode recovery have not been performed.

## Recovery boundary

Warning QC allows existing valid images to assemble and publish despite a failed
content review. The failed artifact from run #36994904577 contains no usable
panel image, so Resume alone cannot recover it. Keep its terminal receipt and
USD 0.0007725 in the date budget. Image recovery requires the existing explicit
new-revision/reconciliation procedure; do not reuse the terminal date/revision
or infer which exact input caused PROHIBITED_CONTENT from the finish reason.

No production DB mutation, provider generation or live SNS/Telegram send was
performed in this review. Attached Kotlin/blog/RSS and investment-os sources are
outside this repository's incident scope.

## Sources

- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36994904577
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36994133690
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36993757414
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36975694115
- https://app.notion.com/p/3ed9208cbdc381d89526df5511460800
- https://app.notion.com/p/3ec9208cbdc3812998a0d27604da745a
