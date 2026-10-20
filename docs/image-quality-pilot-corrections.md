# P3–P6 pilot corrections

Run 39364358460 produced three successful PNGs, but image success did not imply
quality approval. P5 combined the circular environmental signal with the shield.
Reference lettering also survived the no-text instruction. The quality workflow
did not install the Korean font, so preview captions rendered as missing glyphs.

## Corrected behavior

- Newly compiled scene-performance-2 prompts explicitly separate prop identity,
  environmental displays and shot framing. Reference costume and shape remain
  authoritative; lettering on reference surfaces is explicitly excluded.
- `repair-brief` prepares P3–P6 only for the matching debt/vault story facts.
  P3 uses a lower bracing stance, P4 a sideways pivot, P5 a face/shoulder crop
  with weapons below frame and a distinct distant signal, P6 a shield detail
  with fine cracks above the caption area. Narration, cast and outcomes stay intact.
- Existing frozen prompts and reference bytes are not rewritten. A corrected
  brief needs a new revision, candidate registration and human approval.
- Generate installs and checks the CJK font. Python validates the actual Korean
  caption glyphs before any reservation/provider call. Strict assembly checks
  Korean glyphs before producing slides. `ICG_CJK_FONT_PATH` can specify a local
  Noto CJK font for offline rendering.
- `preview` verifies all PNG hashes in the local successful receipt before
  recomposing captions. It has no database or provider calls.

## Offline operator commands

Use private original candidate scripts and artifact receipts, never public logs
for the prompt or canon material:

```bash
python -m scripts.image_quality repair-brief \
  --candidate private/original-candidate-script.json \
  --output private/corrected-brief.json

python -m scripts.image_quality preview \
  --candidate private/original-candidate-script.json \
  --manifest private/download/result.json \
  --artifact-root private/download \
  --output private/repaired-previews
```

The second command fixes captions on existing images; it does not fix the
generated shield or signal. A matching local receipt verifies file integrity,
not human approval or authentic provenance of arbitrary supplied files.

To prepare a new paid candidate with `prepare`, specify `--panels 3,4,5,6`,
a new revision, the original DB source, current base manifest/run/version and
`--budget 0.40` or another explicitly approved cap. Four selected panels need
at least $0.40 in the existing reservation contract. This is a reservation cap,
not a provider price estimate. Do not reuse the approved revision-3 candidate,
its digest, or its successful-call allowance. Cancel/supersede its pending gate
through the existing human workflow when the replacement is ready.

Source assembly metadata is kept for the SQL narrative equality contract;
the old assembly script hash cannot authorize the changed brief. Reassembly
and image/caption review remain required before selection/publication.

## Release boundary

Keep main, production SQL, registered candidates, selection and publication
unchanged until deployment authorization. Unit tests and offline compositing
cannot establish the visual quality of future provider outputs. After deployment,
the new candidate must pass real image review for shield shape/handedness,
display separation, unwanted lettering, narrative continuity and Korean captions.
