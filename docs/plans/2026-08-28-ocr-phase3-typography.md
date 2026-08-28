# OCR phase 3: typography as a junk discriminator — fixture realism, plumbing, measurement

Tier: T3

## Where phases 1-2.5 leave us

- Junk is **correctly-read background prose** — not garbled, not hallucinated. Quality
  and confidence signals carry no information about it.
- **Recurrence is closed.** PR #110 measured a low-recurrence filter: 19.3% relative cut
  against a 30% bar, deleting a required 1-frame overlay while removing zero junk. It is
  `dedup_min_duration` under another name.
- **Frequency is closed by arithmetic.** Real overlay recurs at 0.83, stable-junk
  watermark at 0.75 — eight points apart. No threshold separates them.
- **Recall is fixed** (PR #113): `retained_overlay_recall` 0.3077 -> 1.0. Overlays now
  reach the filters, so precision work is finally falsifiable.

Typography was the remaining candidate: overlays are deliberately styled, background
text is incidental.

## The finding that reshapes this phase

Measured ink-bbox heights from the fixture's literal `cv2.putText` params (bg 235, 640x480):

| string | ink height | contrast | role |
|---|--:|--:|---|
| lorem lines | **20 px** | 193 | junk |
| `SEASON FINALE LIVE NOW` | 26 px | 235 | required |
| `BREAKING NEWS UPDATE` | **15 px** | 232 | required |
| `FLASH SALE ENDS SOON` | **15 px** | 232 | required |
| `STUDIO NINE FEED` | 13 px | 173 | junk (watermark) |
| `SUBSCRIBE` / `@creator_handle` | 15 px | 228 / 230 | junk (chrome) |

**The signal is inverted for 2 of 3 required overlays.** Lowercase prose carries
ascenders and descenders; ALL-CAPS overlays are cap-to-baseline, so at equal `putText`
scale the junk measures *taller*. Any height threshold removing lorem also removes both
short-lived required overlays. Contrast separates nothing — chrome shares the overlays'
exact colour `(0,0,0)`.

Note for whoever implements: `cv2.getTextSize` reports caph=14 for both and would have
hidden this entirely. Only the ink bbox — which is what RapidOCR detection returns —
exposes it. Do not measure with `getTextSize`.

## Why that does NOT settle the question

The fixture renders `BREAKING NEWS UPDATE` and `FLASH SALE ENDS SOON` at scale **0.6,
thickness 1** — the *same nominal size as background prose*. Real burned-in captions,
chyrons and lower-thirds are substantially larger than body text in a screenshot. The
fixture is very likely **understating** the typographic signal.

We cannot check: `tests/fixtures/eval/` holds only `README.md` and `example-gt.json`;
all six real samples are gitignored and `scripts/fetch_eval_samples.py` needs live
network (gallery-dl / yt-dlp against TikTok). Its README baselines are also marked
"verified v0.1.7" — stale, predating both the confidence split and the recall fix.

So the honest position: **the current fixture cannot fairly answer whether typography
discriminates, and neither can this environment.** Phase 3 must fix the fixture before
it can even ask the question.

## Scope

### Step 1 — make the fixture typographically fair

The casing confound is currently doing all the work. Design the fixture in terms of
**measured ink height**, not `putText` scale, and add the adversarial cases:

- **ALL-CAPS background text** — removes the casing confound outright.
- **Large / bold background text** — a headline or sign in the scene. Currently the
  fixture has no large junk at all, which would flatter any height filter.
- **A lowercase real overlay** — required, so casing cannot be used as a proxy.
- **Realistically-sized short-lived overlays** — keep the existing small ones (they are
  a legitimate hard case) but ADD normally-sized ones, so the fixture spans the real
  range instead of only its hardest corner.
- Optionally a low-contrast real overlay.

Every addition needs ground truth with `appearances`. Keep determinism and the
byte-for-byte reproducibility tests.

**State the resulting height/contrast table in this doc.** If, after these additions,
overlays and junk still overlap on both axes, that is the answer and step 3 must not be
forced.

### Step 2 — carry the geometry (internal only, no schema change)

`aggregate_frame_bboxes` (`bbox_aggregator.py:74`) computes `box_height`, `y_center`,
`x_center` and a frame `mean_height` (`:161-177`) and then returns only
`(joined_text, mean_conf)` (`:215-217`). Everything geometric dies at that boundary.

Widen its return to a NamedTuple carrying at least
`(text, mean_conf, mean_box_height, y_center, x_center)`, pass `frame_height` in, and
consume it in `_process_frame` (`rapid_ocr.py:302-312`) **before** `TranscriptSegment`
is constructed.

Hard constraint: **do NOT add fields to `TranscriptSegment`.** `write_json` is
`model_dump_json` (`output.py:66`), so every field is public schema. We changed that
schema once in 0.4.0; a second break for an internal diagnostic is not acceptable. There
is exactly one caller of `aggregate_frame_bboxes` and one test module, so the internal
path is clean.

Note `preprocessor.py:40-42` does grey + CLAHE with **no resize**, so
`box_height / frame_height` is scale-invariant and safe to compute there — but any
contrast feature is measured post-CLAHE, not raw. Say so wherever contrast is reported.

### Step 3 — measure, then decide

Report per-segment normalized height (and contrast if cheap) in the eval harness as a
**diagnostic**, and produce the separation table for the improved fixture: distribution
of the feature for matched (real) vs unmatched (junk) segments.

## Materiality bar — set before running

A typography filter ships ONLY if, on the improved fixture:

1. it cuts final-stage `unmatched_rate` by **>= 30% relative**, AND
2. `retained_overlay_recall` stays **>= 0.95** and `recall` stays **1.0** — no required
   overlay lost, including the deliberately-small and lowercase ones, AND
3. the separation is not an artifact of a single fixture knob: it must hold when the
   ALL-CAPS-background and large-background cases are present.

Real-sample validation is **unavailable** in this environment. Therefore, even if the
bar is met, the filter ships **disabled by default** behind a config knob, documented as
unvalidated on real content. Do not flip a default on synthetic evidence alone.

If the bar is not met: **ship steps 1-2 and the measurement, not a filter.** Step 2 is
independently valuable — it closes the metadata gap that `eval/junk.py:24-28` already
documents, and makes the next hypothesis testable.

## Explicitly NOT in scope

- Any change to `TranscriptSegment` / the public JSON schema.
- `ocr_min_confidence`, `frequency_threshold`, `dedup_*` knobs.
- Recurrence or frequency filtering (closed).
- Detector-model swaps (measured in `2026-07-16-ocr-det-ab.md`; not the lever).
- Semantic/LLM-based discrimination — junk is grammatical prose, so a coherence check
  would pass it. Not this phase.

## Verification

- `bash hooks/run-gate.sh` -> PASS, coverage >= 95%. Report actual numbers (642 baseline).
- Fixture reproducible byte-for-byte across two runs; existing determinism tests extended.
- Height/contrast table for every fixture element, measured from the ink bbox (NOT
  `cv2.getTextSize`), recorded in this doc.
- Before/after `unmatched_rate`, `recall`, `retained_overlay_recall`, funnel — back to
  back in one environment.
- Unit tests for any new geometry plumbing, including one asserting a small required
  overlay survives.

## Risk

The most likely honest outcome is that typography **also** fails to separate, because
real background text can be large and real overlays can be small. If so, say it plainly.
Three candidate discriminators (recurrence, frequency, typography) all failing is a
strong, publishable result about the problem's difficulty — and far more useful than a
filter tuned until a synthetic fixture agreed with it.

## Outcome (executed)

**Materiality bar NOT met. No filter ships.** Steps 1 and 2 (fixture + geometry
plumbing + measurement) shipped; no typography filter, no config knob, no change to
`TranscriptSegment`.

### Step 1 result — improved fixture, ink-bbox height/contrast table

Measured with the same method as the recon note (render each string in isolation on a
235-background canvas at its exact fixture `putText` params; ink bbox via
`np.where(gray < 220)`; contrast = `235 - darkest_ink_pixel`, matching the recon's
values exactly for the phase-2 elements as a sanity check):

| element | role | ink height | contrast |
|---|---|--:|--:|
| lorem background line | junk | 20 | 193 |
| ALL-CAPS background (phase 3) | junk | **15** | 193 |
| large/bold background (phase 3) | junk | **34** | 195 |
| SEASON FINALE LIVE NOW | required | 26 | 235 |
| BREAKING NEWS UPDATE | required, small | 15 | 232 |
| FLASH SALE ENDS SOON | required, small | 15 | 232 |
| TRAFFIC ALERT NOW (phase 3) | required, normal-sized | 26 | 235 |
| storm warning issued now (phase 3) | required, lowercase | **20** | 232 |
| STUDIO NINE FEED | junk watermark | 13 | 173 |
| SUBSCRIBE | junk chrome | 15 | 228 |
| @creator_handle | junk chrome | 15 | 230 |

Required-overlay height range: **[15, 26]**. Junk height range: **[13, 34]** — junk's
range fully *contains* the required range (the ALL-CAPS background element ties the
smallest required overlay at 15px; the large background element at 34px exceeds every
required overlay; the lowercase overlay ties the lorem background at 20px). Height does
not separate.

Contrast: required overlays and the lowercase overlay cluster at 232-235 (color
`(0,0,0)`). Junk chrome (SUBSCRIBE/@handle) clusters at 228-230 — inside the required
band, not below it, because it shares the overlays' exact color. Background junk sits
lower (173-195) but that gap is closed by chrome. Contrast does not separate either, for
the same reason the recon note already found.

### Step 3 result — real-pipeline separation table (not just isolated renders)

Ran the actual OCR pipeline (RapidOCR, CPU, YouTube profile) against the improved video
fixture and collected `SegmentGeometry.normalized_height` at the **raw** stage (before
any filter), split by matched-to-ground-truth vs unmatched:

```
matched (real overlays):   n=24 min=0.0312 max=0.0667 mean=0.0424
unmatched (junk):          n=57 min=0.0312 max=0.0667 mean=0.0408
```

Identical min/max, near-identical means. Real-pipeline detection geometry confirms the
isolated-render table exactly — there is no threshold on normalized bbox height that
separates matched from unmatched segments on this fixture. This directly fails
materiality-bar condition 3 (separation must hold with the ALL-CAPS-background and
large-background cases present); conditions 1-2 were not evaluated further since 3
already fails.

### Baseline pipeline metrics on the improved fixture (no filter — steps 1-2 only)

Same environment, single run, `--funnel --junk --platform-profile youtube`, CPU:

| stage | segments | unmatched_rate | retained_overlay_recall |
|---|--:|--:|--:|
| raw | 129 | 0.8140 | 1.0 |
| post_pattern_filter | 105 | 0.7714 | 1.0 |
| post_frequency_filter | 81 | 0.7037 | 1.0 |
| post_dedup | 32 | 0.7188 | 1.0 |

Overall `recall = 1.0`, `precision = 0.28`. All 5 required overlays (including both
deliberately-small ones, the lowercase one, and the normal-sized short-lived one) matched
at similarity 1.0. This is the "before" state; there is no "after" because no filter was
built — building one to sweep thresholds would have contradicted the instruction not to
tune until a fixture agrees, and the separation table above already shows no threshold
can work.

### A fixture bug this phase caught

The first draft of the phase-3 layout placed two short-lived overlays (`FLASH SALE ENDS
SOON`, `TRAFFIC ALERT NOW`) at y >= 422px, inside the YouTube platform profile's bottom
`ui_exclusion_zones` band (`y >= 0.88 * 480 = 422.4px`,
`panoscribe.platforms.youtube.YOUTUBE_PROFILE`). `RapidOCREngine.extract` masks that band
*before* OCR runs, so both overlays were silently zeroed (recall 0.6) — a masking bug
that looked exactly like a typography-filter problem until traced back frame-by-frame
(raw per-frame OCR had the correct text; only the masked video-mode run lost it). Fixed
by relayouting all fixture elements to stay above y=421 with margin; see the code comment
at `_SHORT_LIVED_A_TEXT` in `scripts/generate_ocr_noise_fixture.py`.
