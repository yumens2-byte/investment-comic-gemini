# Image recovery v3 — predeployment verification

Date: 2026-10-20 KST. Base commit: 887c58951f482b159b670a29c8984fd0d3ebd2fe.

## Local results

| Check | Result |
| --- | --- |
| Full `python -m pytest -q tests` | 1,744 passed, 44.56 seconds |
| New content/recovery tests | 27 passed; included in the full total |
| Ordinary attempt diagnostic SQL | 8 isolated PostgreSQL contracts passed |
| Existing retry SQL | 11 isolated PostgreSQL contracts passed |
| New outcome/recovery SQL | 11 isolated PostgreSQL contracts passed |
| Repository-wide ruff | Passed |
| `git diff --check` | Passed |
| Recovery command `--help` | Passed; no credentials required |

Runtime: Python 3.12.14, pytest 9.1.1, Node 24.19.0, isolated PGlite.
The repository CI uses Python 3.11 and its PostgreSQL/PostgREST service jobs;
its results must be checked separately on the final PR commit.

The initial test setup needed a local SOCKS transport dependency because this
execution environment uses a proxy. `socksio` was installed only in the temporary
test environment. No production dependency changes were needed.

## Review and fault injection

- Reproduced the actual verbose P3 action and its short equivalent; both now flag.
- Contract field types, missing paid-panel coverage, cast changes, action/setting
  hash changes and contradictory final runtime instructions fail before paid work.
- Fault-injected local log failure and reviewed response-file failure; settlement
  occurs first and the paid request is not repeated.
- Known-usage refusal remains terminal while reporting internal settlement;
  unknown usage/over-budget outcomes still freeze the scope.
- Same-token same-result settlement is idempotent; changed results conflict.
- Registration uses a locked exact-source comparison and existing receipts.
  Invalid receipt rolls back the new script. Source/cast/story changes and unknown
  calls block registration. Repeating identical registration is idempotent.
- Missing DB v3 contract blocks before reservation/provider invocation.
- New telemetry distinguishes run attempts, rejects extra private payload fields,
  and is inaccessible to anon/authenticated roles.

## Scope and release hold

No production SQL, feature-flag activation, live recovery registration, paid image
generation, assembly or publication was performed. The incident's live data is
unchanged. Operation approval is still required for rollout and any paid pilot.

Local SQL tests use one PostgreSQL backend. They do not establish multi-session
advisory-lock contention correctness, provider acceptance, actual billing accuracy
or delivery success. Existing database service CI and a separately authorized
operational pilot remain the evidence sources for those respective boundaries.

See [release procedure](image-content-recovery-v3.md) for SQL prerequisites,
feature-flag order, fixed-input recovery preparation and rollback.
