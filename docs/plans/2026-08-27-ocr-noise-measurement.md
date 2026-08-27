# OCR junk segments, phase 1: measurement and baseline

Tier: T3

> **Amendment (phase 2, `docs/plans/2026-08-27-ocr-phase2-stability.md`):**
> adversarial review found this phase's junk metric and fixture were both unsound, and
> phase 2 fixed them. Two claims below are now known WRONG and are corrected here
> rather than silently left in place (the rest of this document's findings and
> methodology stand):
>
> 1. **The "5 of 17 final segments (29%) are junk" headline is wrong.** `is_junk_segment`
>    exempted anything with `duration >= 1.5s`; in images mode a merged >=2-frame dedup
>    cluster crosses that threshold and stops counting as junk while remaining
>    unmatched. Post-dedup precision here was already `1/17 = 0.0588`, implying ~16 of
>    17 segments were actually unmatched (~94%), not 5 (29%) — the phase-1 metric was
>    measuring "junk that also happens to be short," not "junk." Phase 2's
>    `unmatched_rate` (no duration exemption) on a corrected fixture measures
>    `82.6%` final-stage unmatched on the video path (the mode this project actually
>    reports the Known Limitation against) — see the phase-2 plan doc's re-baseline.
> 2. **"Pattern filter 48 -> 48, zero effect" is not evidence about the pattern
>    filter.** `resolve_profile` with a directory/file path (this fixture's source)
>    resolves to `GENERIC_PROFILE`, whose `ui_text_patterns` is `()` — `filter_by_patterns`
>    returns its input unchanged on an empty pattern tuple by construction. The
>    experiment could not have measured anything else. Phase 2's fixture adds UI chrome
>    matching the YouTube profile and runs with `--platform-profile youtube`, at which
>    point the pattern filter does fire (26.1% drop at that stage).
>
> Both corrections are phase-2, PR-1 findings; no filter/pipeline behaviour changed to
> produce them — only the measurement (metric + fixture) was fixed.

## Why this is a measurement task, not a fix

The README's one Known Limitation: on text-heavy backgrounds, varying per-frame
detections defeat cross-frame dedup, survive the frequency filter, and yield dozens of
sub-second `[ON-SCREEN]` artifact segments.

Three constraints make "tune a threshold" the wrong move:

1. `docs/plans/2026-08-26-road-to-v1.md:62-63` states this needs stability-aware
   detection, not another knob, and that three OCR-quality sprints have already been
   spent on knobs.
2. `docs/plans/2026-07-16-ocr-det-ab.md` already A/B-tested detector variants against a
   pre-committed materiality bar. No variant met it. **Swapping detection models is
   measured and is not the lever.**
3. `docs/plans/sprint-7-1-ocr-noise-floor.md` shipped caption masking + fuzzy frequency
   filtering, and explicitly DEFERRED per-region/per-speaker weighting as needing
   "richer segment metadata". That is the nearest prior art to a stability-aware
   approach, and it was deferred, not attempted and rejected.

And critically: **there is no precision metric.** `scripts/eval_ocr.py` and the six
`eval`-marked samples assert recall floors only (e.g. sample-6 `baseline_recall` 0.60).
`eval/funnel.py:9` `FunnelCounts` counts drops across 7 stages but classifies nothing.
Searching `src/panoscribe` for junk / noise_score / text_density / is_background /
overlay returns NOTHING — no noise score, no text-density metric, no
background-vs-overlay discrimination exists.

Tuning against a recall-only metric is how `dedup_min_duration` got lowered from 0.5 to
0.0 in Sprint OCR-Recall (`config.py:118-122`) — a change that improved caption recall
and removed the only floor that suppressed single-frame flicker junk. Without a
precision number, any junk fix risks silently re-breaking recall.

**So phase 1 ships measurement and a baseline. No threshold changes, no filter changes.**

## The structural asymmetry to record

`ui_filter.filter_by_frequency` (:111) drops ON-SCREEN text whose
`cluster_count / frame_count >= threshold` — it only removes text that is TOO FREQUENT.
Nothing anywhere removes text that appears once or twice. Unstable background
detections are, by construction, infrequent. They cannot be caught by the existing
filter no matter how it is tuned.

Note also `pipeline.py:191-193`: the denominator is `ocr_engine.last_frame_count`
(yielded frames, scene-change-reduced), confirmed as the real frequency denominator and
not merely logging. Scene-change gating therefore inflates every ratio.

## Scope

### 1. Define "junk segment" precisely, in a doc

Write the definition down before measuring. Starting characterisation to refine
against real data: an `[ON-SCREEN]` segment that is short-lived, appears in few frames,
is spatially unstable across frames, and does not correspond to deliberate overlay
text. The definition must be operational — computable from data the pipeline already
has, or from data this plan adds.

### 2. A deterministic, committed text-heavy fixture

Do NOT depend on the gitignored eval samples — they are fetched, unavailable in CI, and
the suite skips without them. Instead add a **generator script** that synthesizes a
short video/frame sequence with a text-heavy background (e.g. rendered paragraph text,
slightly jittered per frame to reproduce detection instability) plus a small number of
stable, deliberate overlay captions that MUST be retained.

Commit the generator and its ground truth, not a large binary. The fixture must be
reproducible byte-for-byte from the script so the baseline is meaningful.

### 3. Precision/noise metrics in the eval harness

Extend `scripts/eval_ocr.py` (and `eval/funnel.py` if it fits) with, at minimum:
- precision alongside the existing recall,
- a junk-segment count and rate per the definition from step 1,
- retained-overlay recall, so a junk reduction that eats real captions is visible.

The metrics must be reportable for a single input and comparable across runs.

### 4. Baseline measurement

Run the harness against the synthetic fixture on current `main` and record the numbers
in the plan doc. This is the before-half of the required before-and-after. Include the
`FunnelCounts` breakdown so the stage where junk survives is visible.

### 5. Report the findings

State which pipeline stage the junk actually survives, backed by funnel counts — do not
assert it from theory. Recommend a direction for phase 2 (the actual fix) grounded in
the measurements. Explicitly note whether the data supports the stability-aware
hypothesis or contradicts it.

## Explicitly NOT in scope

- Any change to `ocr_min_confidence`, `frequency_threshold`, `dedup_min_duration`,
  `dedup_similarity_threshold`, or any other knob.
- Any change to filtering logic in `ui_filter.py`, `deduplicator.py`, or
  `bbox_aggregator.py`.
- Swapping or retuning the detection model (already measured; not the lever).
- The phase-2 fix itself.

If the measurement work reveals an obvious one-line bug (as opposed to a tuning
opportunity), report it — do not fix it in this PR.

## Verification

- `bash hooks/run-gate.sh` -> PASS, coverage >= 95%. Report actual numbers; the count
  will rise with new tests.
- The generator reproduces the fixture deterministically across two runs.
- New metric code has unit tests, including a case with known junk and known overlays
  where the expected precision/recall are computed by hand.
- Baseline numbers recorded in the plan doc, with the exact command to reproduce them.

---

## Phase-1 execution record

### Recon correction: precision already exists, but is unasserted

`panoscribe.eval.scoring.score_video` (already on `main` at `c0b102d`, added by an
unrelated earlier sprint) computes `precision` alongside `recall`, and
`scripts/eval_ocr.py` already prints it and exits non-zero when `precision < 1.0`.
So the plan doc's "there is no precision metric" is imprecise: the *metric function*
exists. What is genuinely true, confirmed by reading `tests/test_eval_integration.py`,
is the load-bearing claim — **the six `eval`-marked sample tests assert only
`result.recall >= baseline_recall`; `precision` is printed in the trailing `print()` but
never asserted.** Nothing in CI (which skips the whole `eval` marker per
`pyproject.toml` `addopts`) or in the opt-in local suite fails on low precision. That
gap — no precision floor, no junk metric, no per-stage junk attribution — is what this
phase fills.

### 1. Operational definition of "junk segment"

A junk segment is a final- (or intermediate-) stage `ON-SCREEN`/`BOTH` segment that:

1. does not fuzzy-match (`rapidfuzz.fuzz.ratio(..., processor=str.lower) / 100 >=
   fuzzy_threshold`, default 0.85 — the same convention `dedup_similarity_threshold`
   and `score_video` already use) any *individual* ground-truth expected text, **and**
2. has `duration = segment.end - segment.start < 1.5s`.

Implementation: `panoscribe.eval.junk.is_junk_segment` / `compute_junk_metrics`.

**Why duration 1.5s:** `RapidOCREngine.extract_images` assigns each image exactly a
1.0s span (`start=i, end=i+1`); `extract` (video) assigns `start == end` per sampled
frame, and cross-frame dedup grows the span only when frames merge. A segment shorter
than 1.5s never survived a merge across two or more frames — it is a single-frame
survivor by construction, matching the "short-lived" arm of the plan's starting
characterisation.

**What is deliberately NOT in the definition, and why:** the starting characterisation
also named "appears in few frames" and "is spatially unstable across frames" as junk
signals. Both are **not computable** from the data the post-dedup pipeline retains:
`panoscribe.output.TranscriptSegment` carries `start`/`end`/`text`/`source`/confidence
and nothing else — no per-frame appearance count, no bbox position, no positional
variance. That information exists transiently inside `bbox_aggregator` and
`rapid_ocr._process_frame` per-frame, but is thrown away before `TranscriptSegment`
construction and never re-derived downstream. **This is itself a phase-1 finding,**
not an implementation shortcut: it is independent, code-level corroboration of
`sprint-7-1-ocr-noise-floor.md`'s deferral of per-region/per-speaker weighting as
needing "richer segment metadata" — the metadata genuinely does not exist anywhere in
the current pipeline, at any stage after aggregation. A phase-2 stability-aware
detector must add that provenance (e.g. frame-count and a position/variance summary
per merged segment) before it can implement the "few frames" / "spatially unstable"
arms of the definition. Per-segment additions were deliberately NOT made to
`TranscriptSegment` in this phase — it is a shared model consumed by every output
writer, and this phase changes measurement only, not the pipeline or its data model.

`retained_overlay_recall` is reported separately from `recall`: the fraction of
*required* ground-truth texts with at least one individually-matching segment. In this
phase-1 fixture (see below) it is numerically identical to `recall` (every GT entry is
a deliberate overlay caption and pair/triple joining never applies to a
single-caption GT), but it is computed independently so a future junk-focused change
that accidentally drops a real caption shows up here even once ground truth mixes
overlay and non-overlay required entries.

### 2. Deterministic synthetic fixture

`scripts/generate_ocr_noise_fixture.py` — pure `numpy`/`cv2`, no OCR model, no network.
`generate_frames(num_frames=12, seed=42)` returns 12 in-memory BGR frames plus a
ground-truth dict:

- **Background "junk" text**: a 12-line lorem-ipsum pool; each frame renders a
  **4-line sliding window** starting at a seeded-random offset into the pool, plus
  +/-3px position jitter. The pool/window design was chosen only after an initial
  **position-jitter-only design failed** (see "false start" below) — it is the
  mechanism that actually reproduces per-frame content instability, not merely pixel
  noise on static text.
- **Deliberate overlay caption**: `"SEASON FINALE LIVE NOW"`, fixed position, never
  jittered, shown in 10 of 12 frames (skipped at indices 2 and 7) so its frequency
  ratio (~0.83) stays under the default `frequency_threshold` (0.95) while remaining
  the overwhelming majority signal — a real "stable caption" pattern.
- Ground truth lists **only** the overlay caption, `required: true`. The background
  pool text is lexically unrelated to it (no shared words), so no fuzzy match at
  `>= 0.85` is possible even under OCR noise.

**Determinism**: all randomness comes from `numpy.random.default_rng(seed)` — no
global RNG state is read or mutated (asserted in
`tests/test_generate_ocr_noise_fixture.py::test_does_not_mutate_global_numpy_random_state`).
Verified locally, two independent runs of
`python scripts/generate_ocr_noise_fixture.py <dir>`:
decoded frame arrays are `numpy.array_equal` for all 12 frames, `ground_truth.json`
text is byte-identical, and even the **PNG-encoded bytes** were byte-identical in this
environment (not asserted by the committed tests, since PNG encoder byte-output is not
guaranteed stable across zlib versions/platforms — only the decoded array equality is
asserted, which is the reproducibility property OCR actually depends on).

**False start, reported for transparency:** the first fixture design jittered a single
static 4-line paragraph by +/-3px per frame with no content change. Measured against
it, RapidOCR recognized the identical 4 lines every frame (raw_bboxes=58,
`post_frequency_filter` junk_count **0** — the frequency filter caught 100% of the
"junk"). That result would have been a false negative for this whole measurement
exercise: it showed pixel jitter alone does not reproduce the reported problem, because
`filter_by_frequency` is specifically designed to catch identically-recognized
recurring text. Real background-text junk requires genuinely different per-frame
content (scrolling text, changing content, partial misreads) — which the sliding-window
design now provides.

### 3. Metrics added

`src/panoscribe/eval/junk.py` (new module, unit-tested in `tests/test_eval_junk.py`,
100% covered): `JunkMetrics` (`total_segments`, `junk_count`, `junk_rate`,
`retained_overlay_recall`), `is_matched_to_ground_truth`, `is_junk_segment`,
`compute_junk_metrics`. `scripts/eval_ocr.py` gained a `--junk` flag that computes
`compute_junk_metrics` at four stages — raw (pre-filter), post-pattern-filter,
post-frequency-filter, post-dedup — and attaches the per-stage breakdown to
`EvalResult.junk` (new optional field, default `None`, on `panoscribe.eval.models`;
backward-compatible, mirrors the existing `funnel` field's opt-in pattern).

Hand-computed unit test (`TestComputeJunkMetrics::test_hand_computed_mixed_case`): 4
ON-SCREEN segments, one matching the GT caption (long, 10.0s span) and three
unmatched 1.0s background segments -> by hand `junk_count=3`, `junk_rate=0.75`,
`retained_overlay_recall=1.0`; asserted and passing.

### 4. Baseline measurement

Reproduce command (default config, `PanoScribeConfig()` — no threshold overrides):

```bash
python scripts/generate_ocr_noise_fixture.py /path/to/fixture-dir
python scripts/eval_ocr.py --images /path/to/fixture-dir \
    /path/to/fixture-dir/ground_truth.json \
    --ocr-language en --funnel --junk
```

Measured locally (`RapidOCREngine`, CPU execution provider, `en` language,
`ocr_min_confidence=0.6`, `frequency_threshold=0.95` (GENERIC profile),
`ocr_frequency_min_frame_count=10`, `dedup_similarity_threshold=0.85`,
`dedup_min_duration=0.0`). `ocr_engine.last_frame_count = 12` (all 12 images
processed; images mode always sets it via `processed_count`, so
`filter_by_frequency`'s ratio denominator is the real frame count here, not 0 — this
was explicitly checked, since a `0` denominator would make the frequency filter a
silent no-op and invalidate the whole baseline).

```
recall                          = 1.0
precision                       = 0.0588235294117647   (1/17)
retained_overlay_recall (final) = 1.0
```

Funnel:

| Stage                     | Count | Drop % |
|---------------------------|------:|-------:|
| Raw bboxes (frame-level)  |    58 |      — |
| Post aggregation          |    58 |   0.0% |
| Post extract (segments)   |    58 |   0.0% |
| Post pattern filter       |    58 |   0.0% |
| Post frequency filter     |    58 |   0.0% |
| Post dedup                |    17 |  70.7% |
| Final on-screen / both    |    17 |   0.0% |

Junk (per phase-1 definition) at each stage:

| Stage                   | total | junk_count | junk_rate |
|-------------------------|------:|-----------:|----------:|
| raw                     |    58 |         48 |    0.828  |
| post_pattern_filter     |    58 |         48 |    0.828  |
| post_frequency_filter   |    58 |         48 |    0.828  |
| post_dedup (final)      |    17 |          5 |    0.294  |

### 5. Findings

**Which stage does junk survive?** Pattern filter and frequency filter: **zero
effect** on junk (48 junk segments in, 48 out, both stages — no drop at all). Dedup
is the only stage that reduces junk (48 -> 5), and only incidentally: with a 12-line
pool and a 4-line window over 12 frames, some frames happen to draw overlapping/
identical windows, and those get collapsed by text-similarity dedup. Junk that never
recurs across two dedup-adjacent frames survives all the way to final output — 5 of
the 17 final segments (29%) are junk by the phase-1 definition, and overall precision
on this fixture is a catastrophic 0.059 (only the deliberate caption matches ground
truth). Recall and `retained_overlay_recall` stay at 1.0 at every stage — the
deliberate overlay caption is never harmed by any of this, confirming the fixture
isolates the junk problem from the recall-affecting knobs phase 1 was told not to touch.

**Does the data support or contradict the stability-aware-detection hypothesis
(`road-to-v1.md:62-63`)?** **Supports it, with a precise mechanism.** The measured
funnel confirms the structural asymmetry noted going in: `filter_by_frequency` only
ever removes text that is *too frequent* (`cluster_count / frame_count >= threshold`);
it provably cannot remove text that recurs 0 or 1 times, which is exactly what
unstable background detections look like (48/58 raw segments here are singletons or
near-singletons across the fixture's 12 frames). No threshold retune fixes this — the
predicate itself is one-directional. Dedup's partial (48->5) reduction is a side
effect of this fixture's limited 12-line pool causing accidental window reuse, not a
real defense; in a real video with unbounded scrolling/changing background text, dedup
would see zero repeats and remove nothing. The phase-1 metadata-gap finding under
"Operational definition" above is the second half of the mechanism: even if a future
filter wanted to use frame-count or spatial-stability signals, `TranscriptSegment` does
not carry them past aggregation today, so a threshold-only fix is not just
insufficient, it is not implementable without new segment metadata. This matches
`sprint-7-1-ocr-noise-floor.md`'s deferral rationale exactly.

**Phase-2 recommendation (grounded in the above, not built here):** add per-frame
provenance to the OCR aggregation path — at minimum a frame-appearance count and a
positional-variance summary per pre-dedup detection — and thread it through
`bbox_aggregator`/`rapid_ocr._process_frame` into a new stage that runs *before* (or
instead of) `filter_by_frequency`, gating on "does this text's position/content
recur in a stable way across nearby frames" rather than "is this text frequent overall".
That directly targets the mechanism measured here (asymmetric frequency-only filtering
+ no metadata to detect instability) rather than retuning any existing threshold, which
this phase's baseline shows cannot work by construction.

### One-line bug noticed, not fixed (out of scope per this phase)

None found. (`filter_by_frequency`'s frequency-only asymmetry and the metadata gap
above are architectural gaps, not one-line bugs — no localized off-by-one or logic
inversion was found during this measurement pass.)
