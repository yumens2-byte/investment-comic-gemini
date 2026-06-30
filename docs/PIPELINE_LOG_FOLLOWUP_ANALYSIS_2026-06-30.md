# Pipeline Log Follow-up Analysis (2026-06-30)

## Log Findings

The provided Run Market log completed successfully through STEP 2-6, including narrative generation,
Supabase/Notion persistence, Gemini image generation, and artifact upload. No terminal deployment
failure remained in that run.

The log still showed these operational warnings:

1. `daily_snapshots.data_quality` is not yet present in the deployed Supabase/PostgREST schema.
   The code retried once without that optional field and saved the core snapshot successfully.
2. LunarCrush returned permanent HTTP 402. This only affects optional BTC social sentiment fields;
   the CriticalDataGate passed and the pipeline used the cache/fallback path.
3. `daily_analysis` character-selection observability columns are missing. Before this follow-up,
   the compatibility layer removed one missing column per retry, producing a burst of repeated
   HTTP 400 responses before `analysis_ctx_json` was finally saved.
4. `arc_state.zero_block_just_appeared` is not yet present in the deployed schema. The code retried
   once without that optional field and saved arc state successfully.
5. GitHub Actions emitted Node runtime deprecation warnings from hosted runner/actions internals;
   these did not block artifact upload.

## Additional Code Remediation

The main code issue found in the logs was the `daily_analysis` retry storm. Character-selection
summary columns are an optional observability group. If any member is absent, the deployment is
running ahead of the Supabase migration or schema-cache refresh, so discovering each missing column
one-by-one is wasteful and noisy.

The remediation changes `_update_daily_analysis_schema_compatible()` to strip the complete optional
character-selection summary field set in a single retry while preserving the required
`analysis_ctx_json` payload. This keeps downstream narrative/persist/image stages unblocked and
reduces old-schema behavior from many HTTP 400 responses to one expected compatibility retry.

## Remaining Non-code Actions

Apply and refresh the pending Supabase schema migrations to remove compatibility warnings entirely:

- `migrations/2026_06_20_run_market_critical_fallback.sql`
- `migrations/2026_06_03_character_selection_observability.sql`
- `migrations/2026_06_21_arc_state_zero_block_compat.sql`
