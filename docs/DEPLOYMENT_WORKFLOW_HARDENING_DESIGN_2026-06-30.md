# Deployment Workflow Error Remediation Design (2026-06-30)

## Problem

Scheduled and manually dispatched GitHub Actions workflows mixed two input styles:

- `github.event.inputs.*` in multiple workflows.
- `inputs.*` in `run_market.yml`.

In addition, several workflow `env` entries used a visually subtle `KEY : value` form for
`PUBLISH_NON_MAJOR`. YAML parsers usually normalize this, but it makes workflow review brittle
and can hide deployment/runtime configuration mistakes.

## Design

1. Standardize all workflow-dispatch values on the GitHub Actions `inputs.*` context.
   - This keeps manual workflows readable.
   - It avoids null-event payload assumptions when a workflow also supports `schedule`.
2. Normalize deployment environment keys to canonical `KEY: value` YAML syntax.
3. Add a regression test that scans every workflow under `.github/workflows` for:
   - YAML parseability.
   - No `github.event.inputs` references.
   - No whitespace before a YAML key colon.

## Validation Scope

- Static syntax: Python `compileall`, Ruff, workflow YAML parse tests.
- Regression: full top-level pytest suite.
- Mail secretary package tests, which are outside the top-level pytest `testpaths` default.
