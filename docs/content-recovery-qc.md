# Content recovery QC boundary

The October 2 recovery restored receipted images but did not approve their visual
content. `CONTENT_QC_HOLD:` and any unresolved `_recovery_qc` now stop Resume,
publication preflight and the publication claim, including forced assembly.
Publication CAS also fences the inspected `script_json` to reject stale workers.

Legacy episodes without a recovery review retain their existing checks. A reviewed
recovery requires `_recovery_qc.version=content-qc-1`, `status=PASS`, the exact public
`script_hash`, integer `generation_revision`, and `panel_hashes` keyed by the scene
panel indices. `panels_json` must carry the matching `sha256` for every scene.
Resume verifies those hashes against source bytes before writing any slides.
Editing dialogue invalidates the review hash; review the edited script first.
Clear the content-hold error only after the content review passes. Do not remove
review metadata to bypass the check or treat schema validation as visual approval.

## Guest appearance

`config/guest_visuals.yaml` translates the existing April 22 ICG guest design
document, linked in the file. Main hero/villain canon and REF assets are unchanged.
Narrative guest prompts and image prompts use the same appearance contract.
Missing guest contracts stop prompt compilation rather than inventing a design.
Sector Phantom's source tickers and Momentum Rider's line markings remain abstract
under the existing no-readable-typography rule.

Sentinel Yield wears black-and-white judge robes and carries a yield-curve-shaped
sword. Neither the restored turquoise projection nor the silver robot satisfies
that design. P1–P4 need scene repair, not approval based on matching paid receipts.

The legacy runtime style line prohibiting flat cel shading contradicts the
checked-in `style_lock.shading=cel`. Prompt compilation removes that line and adds
a 2D comic rendering lock while retaining the runtime positioning rules.

## Deterministic cards

`TEXT_CARD` always renders the supplied script text and `market_ref` on a neutral
background; it ignores even a present older generated chart. It is an intentional
publishable card (`icg_render_kind=text_card`), distinct from a missing-scene text
fallback, which remains forbidden. `DISCLAIMER` keeps its dedicated renderer.
Both card kinds are excluded from paid image calls while their panel positions
remain in `panels_json` with null paths. Missing scene images still abort the image
stage and strict assembly. Card panels cannot have a character cast.

## October 2 remaining blockers

The provider rejected revision 2 P6 with `PROHIBITED_CONTENT`. The known cost is
$0.0005385. That reason alone does not establish which prompt phrase caused the
rejection. Terminal, reserved and unknown calls continue to block the scope at
both preflight and reservation. This change does not modify receipts, increase
budgets or permit a new revision to bypass that hold.

The revision-3 repair script is an offline proposal, not a persisted or generated
episode. Preserve the original terminal/cost record and reconcile it through a
separately audited recovery procedure before any live attempt. Validate the
inherited story-state baseline before persisting the new candidate. After scene
generation, perform visual QC, bind the exact script and image hashes, then run
strict assembly and publication preflight. The PR itself never sends SNS posts.
