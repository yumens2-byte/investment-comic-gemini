# Image content recovery v3 — implementation and release gate

Base: 887c58951f482b159b670a29c8984fd0d3ebd2fe.
Incident: Run Market 39325628570, episode ICG-2026-10-20-001.
This branch prepares code and isolated tests. It does not repair the live episode,
apply production SQL, generate paid images, assemble or publish.

## Implemented

- Long character-directed attacks no longer bypass the eight-word action check.
- Reviewed `scene-contract-1` binds action, setting, cast, non-contact mode and
  review evidence. Every paid panel must be covered; compositor cards are excluded.
- Contract scenes suppress inherited combat staging. Final runtime style/design
  instructions are inspected as well. Unclear/physical actions require review.
- Reviewed fixed prompts must contain their exact action and setting. The existing
  model/REF/fingerprint checks are retained; original rejected inputs are not rewritten.
- Completed no-image outcomes settle before local log/response-file I/O. Detailed
  evidence errors cannot create a second paid call. Provider exceptions in public
  image logs use the exception type rather than raw request-bearing messages.
- Versioned settlement RPC gives a settled content refusal its own hold code,
  supports identical settlement retries and rejects conflicting results. Reservations,
  unknown outcomes, rejected inputs and lifetime budgets remain protected.
- Separate per-run telemetry records even zero-image holds without changing
  `episode_assets.status` or its verified PNG artifact pointer.
- Offline candidate preparation and atomic compare-and-set registration use the
  existing terminal-recovery receipts. Failed authorization rolls back the candidate.

## Before merge / release

1. Require CI: lint/unit tests, ordinary diagnostics SQL, retry SQL, outcome/recovery
   SQL, existing PostgreSQL narrative/recovery and publication contracts.
2. Verify deployed SQL versions and schema on the intended production project.
   Files under `docs/sql` are deployment proposals, not proof of deployment.
3. Apply **after explicit operational approval**, in a transaction where supported:
   existing revision/recovery/retry/ordinary diagnostic prerequisites if absent,
   then `docs/sql/image-generation-outcome-v3.sql` and
   `docs/sql/image-generation-register-recovery-v3.sql`. Do not reapply old
   non-idempotent DDL blindly. Never delete historic calls or reset budgets.
4. Deploy code. Keep `ICG_IMAGE_OUTCOME_V3_ENABLED=false` until SQL is verified.
   The release configuration in `run_market.yml` is explicitly set to true only
   after the production DB contract is deployed and its capability verified.
5. Enable that workflow environment setting only after the new capability RPC is available.
   Missing v3 DB capability fails before image reservation/provider invocation.
6. Do a read-only preflight, then separately authorize and inspect one paid pilot.
   Passing local checks cannot guarantee provider acceptance.

## Prepare a recovery (no provider or DB writes by default)

Export the exact current `episode_assets.script_json`, including its state candidate,
to a private file. The earlier narrative artifact lacks later persistence metadata
and must not be substituted. Confirm the terminal token, usage-based cost and REF
hashes from private diagnostic records before attempting registration.

Create a private JSON object keyed by each paid panel index. Each item contains:

```json
{
  "1": {
    "action": "The figures stand apart and observe a separate display.",
    "setting": "A fictional control room with abstract diagrams.",
    "prompt_text": "A fictional control room with abstract diagrams. The figures stand apart and observe a separate display. Preserve the approved reference identities.",
    "contract": {
      "visual_mode": "SYMBOLIC_STANDOFF",
      "interaction": "OBSERVE_SEPARATE_DISPLAY",
      "target_kind": "DISPLAY",
      "physical_contact": false,
      "weapon_discharge": false,
      "injury": "NONE",
      "required_story_facts": ["unresolved_standoff"]
    }
  }
}
```

This example is a shape illustration. Supply all six reviewed paid scenes for the
incident and preserve the existing cast, canonical props, story and thread evidence.
Change scenes themselves; do not disguise violent content or lower safety settings.
The preparation tool fills cast, text hashes and REF identities from the canonical
assets. Prompts must be complete reviewed instructions; they are not rebuilt from
mutable Notion pages during recovery.

```bash
python -m scripts.prepare_image_recovery \
  --source /private/current-script.json --scenes /private/reviewed-scenes.json \
  --revision 2 --actor operator \
  --note 'Reviewed non-contact scenes; preserve cast and public story evidence.' \
  --output /private/candidate-revision-2.json
```

Revision 2 is an example, not an assertion that it remains unused. Preparation
validates all panels and REF hashes, writes a new mode-0600 file and refuses a path
under public `output/`. Existing output files are not overwritten. No API/DB call
occurs in the default preparation path.

Registration is a separate, explicit live mutation. After review and operational
authorization, rerun preparation with a new private output path and append
`--register --confirm REGISTER_REVIEWED_RECOVERY --terminal-token <actual-token>
--observed-cost <verified-usage-calculation>`. Use existing server credentials;
never commit them. The RPC compares the current script with the exported source,
preserves public story/cast, advances an unused revision and issues the receipt
atomically. A stale source, unknown call, bad receipt or changed fingerprint blocks it.

Only then run `stage=image` for the same date/revision, with the original artifact
run ID for restoration. Do not rerun `all` or `recovery` and regenerate the narrative
after registration. Assembly and publication remain separate gated operations.

## Rollback and limits

Disable new paid executions, inspect in-flight reservations, then switch off the
workflow outcome setting and roll back code if needed. Keep the additive SQL, diagnostics and
all receipts. A terminal/unknown row must not be cleared as a rollback shortcut.

Local PGlite contracts execute real PostgreSQL SQL/PLpgSQL in one backend; queued
reservations are not evidence of multi-session advisory-lock contention testing.
Provider acceptance, actual provider billing and live delivery need a separately
authorized operational pilot. No refusal-rate reduction percentage is claimed.

Per-run telemetry replaces the design's proposed `episode_assets.image_state`
columns: a separate table avoids changing existing publication selection and keeps
independent attempt histories from overwriting each other. Contract rollout is
explicit via reviewed scripts; legacy scripts retain compatibility and the improved
action checks. No automatic scene rewriting or unreviewed retry loop is introduced.
