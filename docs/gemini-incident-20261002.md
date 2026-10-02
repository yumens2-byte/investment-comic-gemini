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

## Requirements and implementation

1. Preserve provider finish reason, panel and measured/unknown cost even
   when settlement RPC returns HOLD. Log safe structured usage fields and
   an evidence path before settlement; do not log prompts, bytes or credentials.
2. Keep terminal and missing-usage outcomes fail-closed, with one paid
   attempt. Preserve the original ledger error in the exception chain.
3. Surface existing content QC reason, normalized to one line and bounded
   to 500 characters. No QC threshold, receipt or publication bypass.

Changed source: engine/image/gemini_client.py, engine/quality/content_qc.py.
Changed tests: tests/test_image_adapter_guard_v2.py,
tests/test_content_recovery_qc.py. This document is the fifth changed file.

Regression tests reproduce the observed PROHIBITED_CONTENT/cost outcome
with a production-shaped ledger HOLD, ensure one reservation/request and
no output, verify unknown cost remains unknown, and check bounded QC diagnostics.
Targeted adapter/content tests: 43 passed. Ruff and whitespace check passed.
Full suite: 1,469 passed in 41.00 seconds after installing the missing local
SOCKS proxy dependency (socksio). No repository dependency change was needed.

## Delivery status

The reviewable change contains five files. Upload to
`yumens2-byte/investment-comic-gemini`, branch
`codex/gemini-failure-diagnostics-20261002`, and PR creation/CI verification
were approved by the user. Main deployment and episode recovery are separate
from this diagnostic change. Remote CI results are recorded on the PR.

## Recovery boundary

The software diagnosis fix does not make Gemini's rejected image available.
Do not rerun the same date/revision or remove its terminal receipt. Preserve
USD 0.0007725 in the date budget. Review the rejected scene/reference and
provider feedback, then use the existing explicit reviewed-recovery contract
for a new narrative/image revision and immutable terminal acknowledgement.
Do not rewrite prompts to evade provider controls. Unknown details of which
input triggered PROHIBITED_CONTENT cannot be inferred from the finish reason.

The historical QC gate requires a reviewed current script and exact panel
hashes before assembly/publication. Force and narrative-only flags do not
release it. The current failed artifact has no usable panels, so Resume is
not an image-recovery mechanism. A clean DB error is not QC approval.

No production DB mutation, provider generation, SNS send or QC approval
was performed in this review. Attached Kotlin/blog/RSS and investment-os
sources are outside this repository's incident scope.

## Sources

- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36994904577
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36994133690
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36993757414
- https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/36975694115
- https://app.notion.com/p/3ed9208cbdc381d89526df5511460800
- https://app.notion.com/p/3ec9208cbdc3812998a0d27604da745a
