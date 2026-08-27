# OCR junk segments, phase 2: fix the measurement, then earn the filter

Tier: T3 (revised down from T4)

> **This plan was substantially rewritten after adversarial review.** The first draft
> proposed carrying spatial-stability metadata and adding a low-frame-count filter. Two
> independent challenges showed that mechanism is contradicted by phase 1's own data.
> What follows replaces it. The rejected approach and why it failed are recorded at the
> bottom, because the reasons are the most valuable output of the review.

## What actually survives from phase 1

**The diagnosis holds, and it is code-level, not fixture-dependent.**
`ui_filter.filter_by_frequency` (`ui_filter.py:110`) drops ON-SCREEN text when
`cluster_count / frame_count >= threshold`. It is one-directional: it can only remove
text that is TOO FREQUENT. Infrequent text is structurally unreachable at any threshold.
Worse, the ratios are close together — lowering the bound far enough to catch a
~0.5-ratio background line would also kill a ~0.83-ratio real overlay. The metadata gap
is real.

**Almost nothing else from the phase-1 numbers is usable.** See the audit below.

## Why the measurement must be fixed first

1. **The junk metric's duration arm is tautological or inert, depending on mode.**
   `is_junk_segment` (`junk.py:104-107`) exempts anything with duration >= 1.5s.
   Pre-dedup, images mode gives every span 1.0s, so the arm never fires and
   junk == unmatched. Video mode's `extract()` sets `start == end` (duration 0), so it
   is inert there too. The metric therefore behaves DIFFERENTLY between the two modes.

2. **"Dedup 48 -> 5" is mostly reclassification, not removal.** In images mode a merged
   cluster of >=2 frames spans >=2.0s, crosses the 1.5s exemption, and stops being
   counted as junk while remaining unmatched noise. Post-dedup precision 0.0588 = 1/17
   implies ~16 of 17 segments are unmatched. **The true noise rate is ~94%, not the 29%
   phase 1 reported.** Any materiality bar set against the current metric would be set
   against a number that moves when segments merge.

3. **"Pattern filter 48 -> 48" is a null experiment.** `resolve_profile` with a
   directory path returns `GENERIC_PROFILE` (`registry.py:37-38`) whose
   `ui_text_patterns` is `()` (`base.py:67,71`), and `filter_by_patterns` returns input
   unchanged on empty patterns (`ui_filter.py:96-97`). Zero effect was guaranteed by
   configuration. It is not evidence about the pattern filter.

4. **The baseline never exercised the reported failure path.** It ran `--images` ->
   `extract_images`: `mask_rects` always `[]`, no scene-change gating, no caption
   masking. The README's Known Limitation is about VIDEO.

5. **`retained_overlay_recall` cannot guard a regression.** One ground-truth entry, and
   the predicate is ">=1 matching segment" (`junk.py:145-154`). Recovering a caption in
   1 of 10 frames scores 1.0. It is pinned at 1.0 for any filter that does not delete
   the overlay entirely — precisely the regression we most need to detect.

6. **Not reproducible across environments.** `rapidocr>=3.8,<4.0` (`pyproject.toml:44`)
   with runtime-downloaded weights; only the decoded fixture arrays are deterministic.

## Scope

### Step 1 — make the metric mean something (no behaviour change)

- Remove the duration arm from the junk definition, or report unmatched-rate directly
  as the headline. Junk must be defined identically in video and images mode.
- Make `retained_overlay_recall` sensitive: score per-appearance rather than
  ">=1 match", so partial destruction of an overlay is visible.
- Keep the old metric alongside if useful for continuity, but the NEW one is what any
  bar is set against.
- Update `tests/test_eval_junk.py` with hand-computed cases, including one where a
  merged multi-frame cluster must still count as noise (the exact case the 1.5s
  exemption was hiding).

### Step 2 — make the fixture able to detect a regression

The current fixture cannot fail the filters we care about. Add, with ground truth:
- **short-lived REAL overlays** (1-2 sampled frames) that MUST be retained — at 1 fps
  with scene-change gating, burned-in subtitles and fast lower-thirds land here. Without
  these, any low-count filter scores perfectly while destroying real captions.
- **stable junk** — a static watermark / channel bug / background signage that persists
  across most frames at a ratio below the frequency threshold. This is junk the
  recurrence signal cannot catch, and its absence flatters any recurrence-based filter.
- **UI chrome** matching a real platform profile, so the pattern filter is testable at
  all rather than null by construction.
- Exercise the **video path**, not just `--images`, so scene-change gating and zone
  masking participate.

### Step 3 — re-baseline honestly

Re-run with the corrected metric on the corrected fixture, video path, back-to-back in
one environment (weights are downloaded at runtime, so cross-environment comparison is
invalid). Record the numbers and the exact command. Expect them to look much worse than
phase 1's 29%; that is the point.

### Step 4 — only then, consider a filter

The candidate signal is **content recurrence**, NOT geometry. Phase 1's false start
showed a position-jitter-only fixture produced zero surviving junk — spatial instability
did not generate the failure. The junk comes from content novelty.

Note that `filter_by_frequency` ALREADY computes cross-frame fuzzy text groups
pre-dedup. A low-recurrence bound is the same computation with the inequality flipped,
so this belongs inside/next to that function, pre-dedup, reusing its clustering — not a
new stage.

Two hard constraints on any such filter:

- **It must explain why it is not `dedup_min_duration` reincarnated.** At 1 fps,
  `min_duration=0.5` drops exactly single-frame clusters, i.e. it IS an "appeared in
  >=2 frames" filter. `config.py:118-122` records it removed in Sprint OCR-Recall as a
  recall-killer for sub-second captions. Rebuilding that mechanism under a new name
  without addressing the recorded regression is not acceptable.
- **Use an absolute count, not a ratio.** The denominator `last_frame_count` is deflated
  by scene-change gating (`pipeline.py:191-193`), so a lower ratio bound is unstable.
  Follow the existing `ocr_frequency_min_frame_count` guard pattern.

Set the materiality bar **in this plan before running**, in the style of
`docs/plans/2026-07-16-ocr-det-ab.md`. Proposed: a filter ships only if it cuts the
unmatched-segment rate by >= 30% relative while losing **zero** required short-lived
overlays on the corrected fixture, and shows no recall regression on the real
`eval`-marked samples.

If the bar is not met, ship steps 1-3 and NOT the filter. That is a legitimate outcome.

## Sequencing

- **PR 1** — steps 1-3. No production behaviour change; eval/metric/fixture only.
  Independently valuable: it makes the problem honestly measurable and corrects a
  materially wrong published number.
- **PR 2** — step 4, only if the bar is met.

Do not bundle them.

---

## PR 1 execution record

### Metric decision (step 1)

Kept `is_junk_segment`/`JunkMetrics.junk_rate` for phase-1 continuity, but added
`is_unmatched_segment`/`unmatched_count`/`unmatched_rate` as the **authoritative**
metric: ON-SCREEN/BOTH, no GT fuzzy-match, no duration exemption. `retained_overlay_recall`
gained an additive, backward-compatible `ExpectedText.appearances: list[(start, end)]
| None` field on the ground-truth model — when present, each declared appearance is
scored independently (partial destruction of a recurring overlay is now visible as a
fractional score instead of pinned at 1.0 the instant one appearance survives); when
absent (all six real `eval`-marked samples), the original coarse ">= 1 match in
[start, end]" behaviour is unchanged, so existing ground-truth files are not a breaking
migration. See `src/panoscribe/eval/junk.py` module docstring and
`tests/test_eval_junk.py` (hand-computed cases, including the merged-cluster case that
the 1.5s exemption was hiding).

### Fixture (step 2)

`scripts/generate_ocr_noise_fixture.py` gained, on top of the phase-1 sliding-window
background + main stable overlay:

- two short-lived REQUIRED overlays (`BREAKING NEWS UPDATE` — 1 frame;
  `FLASH SALE ENDS SOON` — 2 frames), ground-truthed via `appearances` as exact
  per-frame point windows;
- a stable-junk watermark (`STUDIO NINE FEED`, shown in 9/12 frames — ratio 0.75, below
  the default 0.95 frequency-filter threshold, never in ground truth);
- UI chrome (`SUBSCRIBE`, `@creator_handle`) positioned OUTSIDE the YouTube profile's
  `ui_exclusion_zones`, so `--platform-profile youtube` makes the pattern filter
  testable instead of the null (`GENERIC_PROFILE`, empty patterns) experiment phase 1
  ran;
- a `write_video_fixture` path (`--video`) writing a single lossless FFV1-in-AVI file at
  1.0 fps (matches `ocr_sample_fps`'s default so sampled timestamp `i` == generator
  frame index `i`), so scene-change gating and zone masking actually participate.
  Verified lossless round-trip (`tests/test_generate_ocr_noise_fixture.py::TestWriteVideoFixtureDeterminism`)
  and byte-identical output across two independent runs with the same seed.

### Re-baseline (step 3)

Both runs below used the same environment, same fixture generator invocation shape,
back-to-back (`PanoScribeConfig()` defaults, `ocr_language=en`; RapidOCR fell back to
`CPUExecutionProvider` at runtime in this environment — a missing `cublasLt64_12.dll`
for the CUDA execution provider — so both runs used CPU, which is the fair
apples-to-apples comparison since neither leg used CUDA).

**Video path (the corrected metric AND corrected fixture, `--platform-profile youtube`
— this is the number that replaces phase 1's 29%):**

```bash
python scripts/generate_ocr_noise_fixture.py /path/to/fixture-dir --video
python scripts/eval_ocr.py /path/to/fixture-dir/fixture.avi \
    /path/to/fixture-dir/ground_truth.json \
    --ocr-language en --platform-profile youtube --funnel --junk
```

```
recall                          = 0.3333333333333333   (1/3 required texts coarse-matched)
precision                       = 0.17391304347826086
retained_overlay_recall (raw)   = 0.3076923076923077    (4 of 13 declared appearances)
retained_overlay_recall (final) = 0.3076923076923077
```

| Stage                     | total | junk_count | junk_rate | unmatched_count | unmatched_rate |
|---------------------------|------:|-----------:|----------:|-----------------:|---------------:|
| raw                       |    46 |         42 |    0.913  |               42 |          0.913 |
| post_pattern_filter       |    34 |         30 |    0.882  |               30 |          0.882 |
| post_frequency_filter     |    34 |         30 |    0.882  |               30 |          0.882 |
| post_dedup (final)        |    23 |         14 |    0.609  |               19 |          0.826 |

Funnel: raw_bboxes 46 -> post_pattern_filter 34 (pattern filter DID fire this time —
`SUBSCRIBE`/`@creator_handle` matched the YouTube profile's patterns, unlike phase 1's
null experiment) -> post_frequency_filter 34 (no additional drop) -> post_dedup 23.

**Note on `junk_rate` vs `unmatched_rate` at raw/pattern/frequency stages:** they are
numerically identical pre-dedup in video mode, by construction — `RapidOCREngine.extract`
always sets `start == end` (duration 0), so `is_junk_segment`'s duration arm never fires
pre-dedup regardless of the exemption threshold. They diverge only post-dedup
(14 vs 19) once merged spans cross the old 1.5s exemption -- those extra 5 segments are
exactly the case the phase-1 metric was blind to.

**Cross-check — same corrected metric, phase-1-style images fixture + generic profile
(isolates "metric changed" from "fixture changed"; not the authoritative baseline,
included for attribution):**

```bash
python scripts/generate_ocr_noise_fixture.py /path/to/fixture-dir
python scripts/eval_ocr.py --images /path/to/fixture-dir \
    /path/to/fixture-dir/ground_truth.json --ocr-language en --funnel --junk
```

```
recall = 1.0, precision = 0.15789473684210525, retained_overlay_recall = 1.0 (all stages)
```

| Stage                   | total | junk_count | junk_rate | unmatched_count | unmatched_rate |
|-------------------------|------:|-----------:|----------:|-----------------:|---------------:|
| raw                     |    94 |         81 |    0.862  |               81 |          0.862 |
| post_pattern_filter     |    94 |         81 |    0.862  |               81 |          0.862 |
| post_frequency_filter   |    70 |         57 |    0.814  |               57 |          0.814 |
| post_dedup (final)      |    19 |          4 |    0.211  |               16 |          0.842 |

Images mode processes all 12 frames (no scene-change gating: `raw_bboxes=94` vs the
video run's `46`) and every appearance of every overlay is individually recognised, so
`retained_overlay_recall` stays 1.0 at every stage here — the video run's 0.31 is not a
metric artifact, it is scene-change gating (Phase 2.5, unrelated to this PR and
explicitly out of scope to change) skipping some of the frames the short-lived overlays
and a majority of the main overlay's appearances land on. That interaction (scene-change
gating vs. short-lived real captions) is a genuine finding worth a follow-up
investigation, not fixed here.

**Headline correction:** phase 1 reported 29% junk at final output
(`docs/plans/2026-08-27-ocr-noise-measurement.md`). Under the corrected fixture, corrected
metric, video path: final-stage `unmatched_rate = 0.826` (82.6%), an order of magnitude
worse than 29% and directionally consistent with the pre-dedup `unmatched_rate` swing this
PR predicted (post-dedup precision `1/17 = 0.0588` in phase 1 already implied a ~94%
true noise rate; the corrected number lands in the same neighbourhood once measured
directly instead of inferred). Even the metric-only cross-check on the OLD-style images
fixture (`unmatched_rate = 0.842` final) is far worse than 29% — most of the gap between
29% and ~83-84% is the metric fix (removing the duration exemption), not the fixture
change; the fixture change is what makes `retained_overlay_recall` honest (0.31 on
video vs. a structurally-pinned 1.0 in phase 1) and makes the pattern filter testable at
all (26.1% drop at `post_pattern_filter` vs. phase 1's guaranteed 0%).

## Validation on real content is a blocker, not a risk

The synthetic fixture is generated with the same assumptions as the filter, so agreement
between them proves little. The six real `eval`-marked samples
(gitignored, fetched via `scripts/fetch_eval_samples.py`) are required for the recall
side of the bar. If those assets are unavailable, step 4 does not proceed.

## Rejected approach, and why (kept deliberately)

The first draft proposed: carry per-segment frame-count AND spatial-stability
(bbox centroid variance / IoU) metadata through aggregation, then filter segments that
are both low-count and spatially unstable.

It was rejected because:

1. **The stability signal is undefined where it is needed.** Junk surviving to output is
   single-appearance; cross-frame variance requires >=2 appearances. The junk that DOES
   recur is what dedup already removes.
2. **Phase 1 already disproved the geometry hypothesis** — the jitter-only fixture
   produced zero surviving junk.
3. **The metadata claim was half wrong.** `_process_frame` (`rapid_ocr.py:305-317`)
   already emits one segment per line per frame with `start == end == timestamp`;
   pre-dedup segments ARE per-frame records. Only geometry is discarded by
   `aggregate_frame_bboxes`. Step 1 as originally scoped was largely redundant, and T4
   was the wrong tier.
4. Caveat retained for whoever implements recurrence counting: `cluster_count` is an
   OCCURRENCE count, not a frame count — the aggregator keeps non-overlapping same-text
   boxes within one frame. It needs per-frame key dedup to become a true frame count.
