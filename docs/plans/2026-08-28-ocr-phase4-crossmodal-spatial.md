# OCR phase 4: cross-modal rejected on design grounds; spatial+size measured

Tier: T3

## Standing position

Four discriminators closed by measurement: detector-swap
(`2026-07-16-ocr-det-ab.md`), frequency (structurally one-directional), recurrence
(PR #110), typography (PR #116 — junk ink-height [13,34]px fully contains required
[15,26]px; real-pipeline normalized-height min/max identical between matched and
unmatched).

Two candidates remain. This phase resolves both.

## Part A — cross-modal: REJECTED on design grounds, before implementation

### What `merge_channels` actually does

`output.py:212-350`. For each SPEECH segment it finds temporally overlapping OCR
segments (`_overlaps`, inclusive, doc `:222`), scores
`fuzz.WRatio(sp.text, oc.text, processor=str.lower)` (`:311`), keeps candidates at or
above `merge_similarity_threshold * 100` (`config.py:134`, default 0.85), takes the best
(ties -> earliest `ocr.start`, `:317-319`), and emits `source="BOTH"` carrying
`text=speech.text` — **the OCR text is discarded** (`:229-236`). Each OCR segment is
consumed at most once (`:330`).

### Why it cannot be a junk filter

The signal is **anti-correlated with the thing we want to keep.**

The fixture's five required overlays — `SEASON FINALE LIVE NOW`, `BREAKING NEWS UPDATE`,
`FLASH SALE ENDS SOON`, `TRAFFIC ALERT NOW`, `storm warning issued now` — are chyrons,
alerts and CTAs. None is spoken. That is not a fixture artifact: titles, lower-thirds,
watermarks, CTAs and channel bugs are, in general, *not read aloud*. They are on screen
precisely because they carry information the audio does not.

So "absence of a speech match" would classify essentially every deliberate overlay as
junk. Meanwhile background prose that speech happens to mention within an overlapping
window would score above the cutoff and be **promoted** — junk endorsed.

Two further structural limits, both grounded in the code:

- Silent or music-only video: `if not speech: return list(ocr)` (`output.py:277-278`).
  The signal is simply absent, so any filter depending on it must no-op — meaning it
  cannot help on exactly the content where OCR is the only channel.
- `merge_channels` runs *after* dedup in the pipeline and discards the OCR text on
  merge, so it is positioned as a **promotion** step (ON-SCREEN + SPEECH -> BOTH), not a
  demotion step. Repurposing it as a filter inverts its role.

### Conclusion

Cross-modal correspondence is a legitimate **confirmation** signal — which the pipeline
already uses, correctly, to promote to `BOTH`. It is **not** a junk discriminator, and
no amount of fixture work would make it one. Rejected. Do not implement.

### What it would have cost to find out empirically

Recorded so nobody re-opens this cheaply: the fixture has no audio track, and
`cv2.VideoWriter` (`generate_ocr_noise_fixture.py:479-501`) has no audio API — muxing
would need an ffmpeg step. `scripts/eval_ocr.py:152` is explicitly "OCR pipeline (no
ASR, no merge)"; it imports neither whisper nor `merge_channels`. A fair test would also
need overlays that ARE spoken and junk deliberately mentioned in speech. That is a
substantial fixture and harness build to confirm a conclusion the code already implies.

## Part B — spatial-position consistency combined with size: measure it

### Why the current fixture cannot answer this

Every non-background element is drawn at hardcoded coordinates: required overlays,
chrome, both phase-3 background-junk lines, and `STUDIO NINE FEED`
(`_STABLE_JUNK_X=380`, `_STABLE_JUNK_Y=253`, `:186-189`, unjittered `:367-371`). Jitter
(`:252-253`) is applied **only** to the sliding lorem window — which is the one thing
`filter_by_frequency` already catches.

So position-stability is near-constant across both classes: the statistic would be
degenerate, and any apparent separation would come from the background window alone.

### The counterexample already in hand

`STUDIO NINE FEED` is perfectly position-stable junk at ink height 13 — the *smallest*
element in the table, below every required overlay. Stability keeps it; size keeps it.
It is a direct counterexample to the conjunction, already present.

### Scope

1. **Make the fixture non-degenerate for position.** Add, with ground truth and
   `appearances`:
   - a **position-unstable REQUIRED overlay** — e.g. a scrolling ticker or a
     slide-in lower-third that moves between frames. This is realistic content and is
     currently absent; without it, "stable => real" is untested.
   - keep `STUDIO NINE FEED` as the stable-junk counterexample.
   Determinism and byte-for-byte reproducibility tests must still hold.

2. **Compute a position-stability statistic per text cluster.** Phase 3 already exposes
   `SegmentGeometry` (`rapid_ocr.py:41-62`: text, start, end, normalized_height,
   y_center, x_center) as an opt-in parallel diagnostic consumed by
   `scripts/eval_ocr.py:155,166,169,236-244`. Use it. Cross-frame identity must reuse the
   existing fuzzy clustering (`ui_filter.py:111-175`, `fuzz.ratio >= 90`) rather than
   inventing a second notion of "same text".

   **Do NOT add a geometry field to `TranscriptSegment`** — `output.py:41-53` is public
   JSON schema and `rapid_ocr.py:44-46` records the deliberate decision not to widen it.
   If threading position through the filters proves to need schema changes, stop and
   report rather than breaking the schema.

3. **Measure the 2D separation** — normalized height x position-stability — for matched
   (real) vs unmatched (junk) segments. Report the joint distribution, not just
   marginals: the question is whether the *combination* separates where neither does
   alone.

### Materiality bar — set before running

A filter ships ONLY if, on the non-degenerate fixture:

1. `unmatched_rate` cut by **>= 30% relative** (baseline post_dedup 0.7188), AND
2. `retained_overlay_recall >= 0.95` and `recall == 1.0` — including the
   position-unstable required overlay and the small ones, AND
3. it correctly retains `STUDIO NINE FEED`'s counterexample structure, i.e. the
   separation is not achieved by a rule that only works because stable junk is small.

Real eval samples remain unavailable (gitignored, live-network fetch), so **even if the
bar is met the filter ships disabled by default** behind a config knob, documented as
unvalidated on real content.

If the bar is not met: ship the fixture improvement and the measurement, **no filter**.

### Expected outcome, stated in advance

Likely negative. In real content a sign or caption in a static shot is perfectly
position-stable, and deliberate overlays are usually stable too — so both classes
cluster at "stable". Phase 3 already showed size does not separate. A conjunction of two
non-separating features usually does not separate. Report that plainly if it holds.

## Explicitly NOT in scope

- Implementing cross-modal filtering (rejected above).
- `TranscriptSegment` / JSON schema changes.
- `ocr_min_confidence`, `frequency_threshold`, `dedup_*` knobs.
- Recurrence, frequency, detector swaps, typography (all closed).

## Verification

- `bash hooks/run-gate.sh` -> PASS, coverage >= 95%. Report actual numbers (649 baseline).
- Fixture byte-for-byte reproducible across two runs.
- Joint distribution table recorded in this doc, plus before/after `unmatched_rate`,
  `recall`, `retained_overlay_recall`, funnel — back-to-back in one environment.
- Unit tests for any new statistic, including one asserting the position-unstable
  required overlay survives.
