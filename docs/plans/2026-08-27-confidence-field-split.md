# Split TranscriptSegment.confidence into two typed fields

Tier: T3

## Problem

`TranscriptSegment.confidence` (`src/panoscribe/output.py:30-38`) carries two
incompatible scales depending on which producer built the segment:

- ASR writes a raw, unnormalized Whisper `avg_logprob` — a negative float, roughly
  -3.0..0.0 (`src/panoscribe/asr/whisper.py:180`).
- OCR writes a pixel-match mean score in `[0.0, 1.0]`
  (`src/panoscribe/ocr/rapid_ocr.py:313`).

The field has no docstring; the only semantic note lives ~200 lines away at
`output.py:233-236`, which explicitly observes that mixing the scales would be
meaningless. The value is emitted under the key `confidence` in every JSON transcript
and is therefore already user-visible. A 1.0 release freezes this as a compatibility
promise.

Decision (made by the user): **split into two separately-typed fields.** Breaking, and
pre-1.0 is exactly when to take it.

## Blast radius (verified by recon — treat as exhaustive for `src/`)

**Producers (4):**
| file:line | writes | scale |
|---|---|---|
| `asr/whisper.py:180` | `getattr(s, "avg_logprob", None)` raw | negative float or None |
| `ocr/rapid_ocr.py:313` | `mean_score` from `aggregate_frame_bboxes` | [0.0, 1.0] |
| `output.py:320` (`[BOTH]` merge) | `sp.confidence` — inherits ASR scale verbatim | negative float or None |
| `ocr/deduplicator.py:67` (re-emit) | `mean_conf` computed at `:64-65` | OCR scale |

**Reads (2, both write-back — nothing filters, thresholds, sorts, or formats on it):**
- `ocr/deduplicator.py:64` — scale-blind arithmetic mean over a cluster, written at `:72`.
  Currently correct ONLY because it is fed ON-SCREEN segments exclusively.
- `output.py:320` — copies speech confidence onto the `[BOTH]` segment.

**The two spots a naive split will miss:**
- `merge/llm_cleanup.py:240` and `:378` — `seg.model_copy(update={"text": cleaned})`.
  Confidence survives LLM cleanup unchanged and un-rescored, so a cleaned segment's
  confidence no longer describes its text. The split must decide what happens here.
- `ocr/deduplicator.py:64` — the scale-blind mean noted above.

**Public boundary:** `write_json` (`output.py:48-51`) via `model_dump_json` is the ONLY
output format exposing it. `write_txt` (:54), `write_srt` (:85), `write_markdown`
(:138) do not. No VTT/CSV writer exists. The HTTP API leaks it transitively —
`api/server.py:189` loads the JSON into `Job.result: dict[str, Any]` (`server.py:69`) —
but `result` is untyped, so confidence never appears in the OpenAPI schema. **There is
no typed response model to migrate and no schema promise to break.**

**No CLI flag touches confidence** (`grep confidence src/panoscribe/cli.py` is empty).

## Explicitly NOT in scope

- **`ocr_min_confidence` is not part of this.** Defined `config.py:66` (default 0.6),
  read at `ocr/rapid_ocr.py:277`, passed as `min_confidence=` at `:301`, applied at
  `ocr/bbox_aggregator.py:139` against raw per-bbox scores **before any
  TranscriptSegment exists**. It is a different value at a different layer. Leave it
  and its ~25 references in `tests/test_bbox_aggregator.py` alone.
- There is no ASR-side threshold anywhere; do not invent one.
- Do not add a normalization/reconciliation helper. The point of the split is that the
  two scales are not comparable.

## Scope

1. **Model** (`output.py:30-38`) — replace `confidence: float | None` with two fields
   carrying their scale in the name and a real docstring stating the range and origin
   of each. Field naming must make the scale unambiguous at the call site; the ASR one
   must not be called "confidence" at all, since a log-prob is not one.
2. **Producers** — each writes only its own field. `[BOTH]` merge (`output.py:320`)
   keeps inheriting the speech value into the ASR-scale field; the existing comment at
   `tests/test_output.py:147` records that the anchor is speech, and that stays true.
3. **`deduplicator.py:64-72`** — mean over the OCR field only.
4. **`llm_cleanup.py:240,378`** — decide and implement explicitly, then document the
   choice in the docstring: either carry both fields through unchanged (status quo,
   but now consciously chosen) or clear them, since the text they scored has changed.
   Do not leave this implicit.
5. **Tests** — update the 9 assertions: `test_whisper.py:112-113,238`,
   `test_output.py:33,44,136-148`, `test_rapid_ocr.py:255,305,670`,
   `test_deduplicator.py:60` (+ helper defaults at `:16,:33`). Add a test asserting the
   two fields never both carry a value for a single-source segment, and a JSON
   round-trip test pinning the new key names.
6. **Docs** — update `output.py:233-236` and its echo at `:219`. Add a JSON output
   schema note documenting both fields and their ranges to `docs/architecture.md` or
   `docs/configuration.md`; recon found the output field is currently documented
   NOWHERE user-facing, which is part of how this drifted.
7. **CHANGELOG** — a breaking-change entry with a migration note, written in the same
   style as the existing `OMNI_* -> PANO_*` section in `README.md:308-319`. State the
   old key, both new keys, and each range.

## Verification

- `bash hooks/run-gate.sh` -> PASS, expect 604+ passed and coverage >= 95% (the count
  will rise with the new tests; report actual numbers).
- `grep -rn "\.confidence" src/` -> no stragglers on the old field.
- Produce a real JSON transcript for an ASR-only and an OCR-only input and confirm the
  emitted keys and ranges. If a full pipeline run is impractical, construct the
  segments directly and exercise `write_json`.
- Confirm `GET /jobs/{id}` still serializes (untyped `result` dict, so it should be
  unaffected — verify rather than assume).

## Follow-on (not this PR)

This is a breaking output-format change and should land in a minor bump (0.4.0), with
the version bump and release handled separately.
