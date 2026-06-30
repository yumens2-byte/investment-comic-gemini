# ICG Pipeline Warning Remediation Design (2026-06-30)

## Scope

This note documents the warning classes observed during the 2026-06-30 run and the concrete remediation plan for code and operations.

## Warning classes

| Warning | Root cause | Runtime impact | Remediation |
| --- | --- | --- | --- |
| `Crypto.com get-mark-price 404` | The fetcher used legacy-looking direct endpoints (`public/get-mark-price`, `public/get-index-price`) that are not the documented Exchange v1 REST methods. | Optional crypto basis fields become `Unknown`; retry loop adds delay/noise. | Use `public/get-valuations` with `valuation_type=mark_price` and `valuation_type=index_price`; classify non-transient HTTP statuses as non-retryable. |
| `LunarCrush 402 Payment Required` | API key/plan does not permit the requested endpoint. | Optional social sentiment fields become `Unknown`; retry loop adds delay/noise. | Keep cache/stale fallback behavior; classify non-transient plan/auth/client statuses as non-retryable so the log points at the real issue. |
| `daily_snapshots.data_quality` missing | Code emits the new optional `data_quality` field before the Supabase migration/schema cache is applied. | First upsert fails, schema-compatible fallback saves the core snapshot without the optional field. | Apply `migrations/2026_06_20_run_market_critical_fallback.sql` and refresh PostgREST schema cache. |
| `daily_analysis.character_selection` missing | Code emits character-selection observability fields before the Supabase migration/schema cache is applied. | Summary columns are skipped; `analysis_ctx_json` fallback still persists the context. | Apply `migrations/2026_06_03_character_selection_observability.sql` and refresh PostgREST schema cache. |

## Code design

1. Preserve retries for transient external failures (`408`, `409`, `425`, `429`, `5xx`).
2. Bypass retries for deterministic external failures (`400`, `401`, `402`, `403`, `404`, etc.) using a shared `NonRetryableAPIError` sentinel.
3. Keep optional data semantics unchanged: failed Crypto.com/LunarCrush enrichment still returns `Unknown` rather than blocking the critical data gate.
4. Fix the Crypto.com root cause by calling `public/get-valuations` rather than only suppressing the warning.

## Verification plan

- Unit-test non-retryable sentinel behavior at the shared retry layer.
- Unit-test Crypto.com and LunarCrush HTTP status classification.
- Unit-test the exact Crypto.com `public/get-valuations` request shape.
- Run the full pytest suite to catch regressions in pipeline gates, persistence, and narrative stages.
