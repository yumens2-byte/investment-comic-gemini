# sidestory — New Network side canon (Facebook)

Isolated side track inside the ICG repo. Phase-1 = L-A only (main → side echo).
Main X pipeline is not modified; see boundary rules in `sidestory/__init__.py`.

## Layout
| Path | Role |
|---|---|
| `core/` | pure domain: models, outcome classes, Tue/Thu schedule, echo pack, canon rules, gates |
| `ports/` | Protocol interfaces |
| `adapters/supabase/` | icg_side access + main feed views (no engine imports) |
| `adapters/icg/` | ONLY place allowed to import `engine` (P1, whitelisted symbols) |
| `adapters/facebook/` | Page publisher (P2/P3) |
| `app/` | settings + stage orchestration |
| `migrations/` | `0000_precheck.sql` (read-only), `0001_icg_side_schema.sql` |
| `tests/` | side tests incl. boundary / split-readiness / isolation checks; `db_contract.py` = real Postgres + PostgREST E2E |

## Cadence
Tue/Thu 10:17 KST (`sidestory_run.yml`, inert until repo variable
`SIDESTORY_SCHEDULE_ENABLED=true`). Anchor = same-day published main episode,
else latest unanchored main episode after the previous slot (≤3 days). Main
outcome → side reaction class: VICTORY / DRAW / DEFEAT / NO_BATTLE.

## P0 runbook
1. Supabase SQL editor: run `migrations/0000_precheck.sql` → all `present = true`.
2. Run `migrations/0001_icg_side_schema.sql`.
3. Supabase dashboard → API → exposed schemas: add `icg_side` (if not listed).
4. Actions → "Sidestory Run" → stage `gate` (read-only) → then `echo` with persist=false.
5. Confirm output `gates` all passed (SG-0 skip is normal on non-slot days; use force).

## Secrets used
`SUPABASE_URL`, `SUPABASE_KEY` (P0); `GEMINI_API_SUB_PAY_KEY`, `ANTHROPIC_API_KEY` (P1);
`FACE_PAGE_ID`, `FACE_PAGE_TOKEN` (P2+). X / Telegram channel secrets are never injected.

## Split procedure (after stabilisation)
`git subtree split --prefix=sidestory -b sidestory-split` → new repo; vendor the
whitelisted engine symbols listed in `adapters/icg/__init__.py`; move
`.github/workflows/sidestory_*.yml`; delete `test_drift_against_main_battle_calc`
and DR-1/diff_guard (ICG-coupled checks). The DB (icg_side + views) is unchanged.
