# Run Market image identity recovery

`artifact identity changed` means a date/panel already has paid image calls for
different prompt/model/aspect/reference bytes. Retrying the same revision cannot
fix this. HTTP 200 from `image_generation_inspect` is a successful ledger check,
not permission to regenerate. Never delete receipts or reset the paid-call budget.

Run Market now checks the image ledger before narrative or persistence can
overwrite a started revision. A repeat schedule is blocked in read-only preflight
before data, narrative or paid image work. An image-only resume loads the exact
persisted episode narrative, validates its revision and current thread contracts,
and stops with recovery instructions if the narrative is stale.

For an intentional repair of an unpublished `narrative_done` episode, select
`stage=recovery`, an unused explicit `generation_revision` (2 for the first
repair), and the original `source_artifact_run_id`. Recovery reuses cached analysis,
generates a current-contract narrative, persists its revision/state candidate,
restores only that date's original panels, then runs image generation. The selected
preflight date is pinned across all stages, including artifact restoration.

For the October 2 incident the original source run is `36919762103`. Select
`target_date=2026-10-02`, `generation_revision=2`, `dry_run=false`,
`source_artifact_run_id=36919762103`, `stage=recovery`. Existing completed calls
remain in all budget totals. Matching fingerprints reuse verified originals;
changed panels archive only receipted originals and use the existing v2 adapter.
Unknown billing, pending reservations and terminal outcomes still require manual
reconciliation. The v2 DB adapter must already be deployed.

If recovery stopped after any revision-2 paid call, use `stage=image` with
`generation_revision=2` and the recovery run's source artifact instead of rerunning
recovery and changing the narrative again. No stage here assembles or publishes.
Review the resulting panels and continue through the existing dialogue/assembly
and publication preflight gates separately.
