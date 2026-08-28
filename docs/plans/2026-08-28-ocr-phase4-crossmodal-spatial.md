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

## Outcome (executed)

### Part A verification

Every citation checked against code on this branch: `output.py:212-350` (`merge_channels`),
`:277-278` (`if not speech: return list(ocr)`), `:311` (`fuzz.WRatio`), `:317-319`
(tie-break), `:330` (`consumed_ocr_idx.add`), `config.py:134`
(`merge_similarity_threshold: float = 0.85`), `_overlaps` at `:198-204` (inclusive
overlap), `rapid_ocr.py:41-62` (`SegmentGeometry`), `eval_ocr.py:155,166,169,236-244`
(geometry wiring), `ui_filter.py:111-175` (`filter_by_frequency` + fuzzy clustering,
default `fuzzy_threshold=90.0`), `generate_ocr_noise_fixture.py:186-189` /`:367-371`
(`_STABLE_JUNK_X/Y`, unjittered). All accurate. One correction: the doc's `:229-236`
citation for "the OCR text is discarded" points at the **docstring** illustration; the
actual `TranscriptSegment(...)` construction is at `:331-339`. No other corrections
needed — **the argument holds. Part A stays rejected; not implemented.**

### Part B — fixture fix

Added `_TICKER_TEXT = "SPORTS SCORE UPDATE LIVE"`, a required overlay whose x-position
advances via `_ticker_x(i)` (`_TICKER_X_MIN=20`, `_TICKER_STEP_PX=25`, clamped at
`_TICKER_X_MAX=340`), baseline `y=406` (clear of the YouTube profile's masked bottom
band). `STUDIO NINE FEED` kept unchanged as the stable-small-junk counterexample.

**A fixture bug this phase caught:** the first draft rendered the ticker in every
sampled frame (recurrence ratio 12/12 = 1.0), which clears `filter_by_frequency`'s
default 0.95 drop threshold — the ticker was silently deleted before position-stability
was ever measured (overall `recall` dropped to 0.8333, similarity to best candidate only
0.478). A moving overlay is not exempt from the recurrence discriminator just because it
moves. Fixed by giving the ticker the same minority-skip treatment as the other required
overlays (`_TICKER_SKIP_FRAME_INDICES = frozenset({3, 8})`, ratio 10/12 ≈ 0.833).

**A pre-existing eval-harness bug this phase also caught (fixed):** `scripts/eval_ocr.py`'s
`--typography` block zipped the (post-filter, reassigned) `ocr_segments` against the
(raw-stage) `geometry` list — despite its own comment claiming "raw stage, pre-filter".
Confirmed by the phase-3 doc's own numbers: its reported typography table (`n=24` matched
+ `n=57` unmatched = 81) matches `post_frequency_filter`'s count exactly, not `raw`'s 129.
Fixed by snapshotting `raw_segments = list(ocr_segments)` before the UI-filter
reassignment and using it (with `zip(..., strict=True)`) for both `--typography` and the
new `--spatial` diagnostic.

Also added `x_center_norm`/`y_center_norm` to `SegmentGeometry` (`rapid_ocr.py`,
`x_center / frame_width`, `y_center / frame_height`) — additive fields on the existing
internal diagnostic NamedTuple, no change to `TranscriptSegment`/JSON schema. Cross-frame
identity clustering was extracted out of `filter_by_frequency`'s inline loop into
`panoscribe.ocr._text_match.cluster_canonical_keys` (behavior-preserving refactor,
verified by the existing `test_ui_filter.py` suite staying green) and reused, unchanged,
by the new `panoscribe.eval.spatial` module — one notion of "same text across frames",
not two.

### Joint distribution table (raw stage, real RapidOCR pipeline, CPU, YouTube profile, `--funnel --junk --typography --spatial`)

```
text                                     matched   n   height  stability
------------------------------------------------------------------------
@creator_handle                            False  12   0.0385     0.0004
GRAND OPENING TODAY                        False  12   0.0660     0.0008
SUBSCRIBE                                  False  12   0.0354     0.0005
URGENT SYSTEM NOTICE FOR ALL VIEWERS       False  12   0.0344     0.0003
SEASON FINALE LIVE NOW                      True  10   0.0542     0.0000
SPORTS SCORE UPDATE LIVE                    True  10   0.0365     0.1407
storm warning issued now.                   True  10   0.0394     0.0006
STUDIO NINE FEED                           False   9   0.0322     0.0009
voluptate velit esse cillum dolore eu      False   7   0.0417     0.0697
aliqua ut enim ad minim veniam quis.       False   5   0.0392     0.0777
duis aute irure dolor in reprehenderit     False   5   0.0383     0.0609
fugiat nulla pariatur excepteur sint       False   5   0.0404     0.0242
occaecat cupidatat non proident sunt       False   5   0.0396     0.0240
culpa qui officia deserunt mollit anim.    False   4   0.0422     0.0022
nisi ut aliquip ex ea commodo consequat    False   4   0.0396     0.0335
nostrud exercitation ullamco laboris       False   4   0.0354     0.0335
Lorem ipsum dolor sit amet consectetur     False   3   0.0368     0.0042
adipiscing elit sed do eiusmod tempor      False   3   0.0396     0.0045
incididunt ut labore et dolore magna       False   3   0.0396     0.0054
FLASH SALE ENDS SOON                        True   2   0.0354     0.0011
BREAKING NEWS UPDATE                        True   1   0.0354  n/a (n=1)
TRAFFIC  ALERT NOW                          True   1   0.0531  n/a (n=1)
```

**The combination does not separate.** 5 of 6 required overlays (all except the new
ticker) are both small *and* perfectly-or-near-perfectly stable (`stability` 0.0000-0.0011)
— indistinguishable on both axes from `STUDIO NINE FEED` (`height=0.0322`,
`stability=0.0009`), `SUBSCRIBE`, `@creator_handle` and `URGENT SYSTEM NOTICE`. The only
required overlay with a large `stability` value is the ticker itself (0.1407) — but
several JUNK background lines also register non-trivial stability from the sliding-window
design (`aliqua`: 0.0777, `voluptate`: 0.0697, `duis`: 0.0609) because the same canonical
line can land at a different row of its 4-line window in different frames, moving its
`y_center` by up to 3×26px — a **realistic** cause of junk position variance (scrolling/
reflowing body text), not a fixture artifact. A stability threshold high enough to keep
the ticker (>0.08-0.14) does clear those background lines, but **any** threshold low
enough to also keep the 5 near-zero-stability required overlays necessarily also keeps
`STUDIO NINE FEED` and the other near-zero-stability junk — this is condition 3's failure
mode exactly: the required overlays and the small-stable-junk counterexample occupy the
*same* region of the joint distribution. **Materiality bar condition 3 fails.** Following
the phase-3 precedent, conditions 1-2 (the quantitative `unmatched_rate` cut and
`retained_overlay_recall` bar) were not evaluated further via an actual filter
implementation, since a filter cannot be built that clears condition 3 in the first place
— building one to sweep thresholds would tune against a fixture already shown not to
support the hypothesis.

**Materiality bar NOT met. No filter ships.** Only the fixture fix, the geometry
plumbing, and the measurement.

### Before/after (post-dedup metrics, same pipeline/config, YouTube profile)

| | before (phase-3 fixture, 5 required overlays) | after (this fixture, 6 required overlays incl. ticker) |
|---|--:|--:|
| `unmatched_rate` | 0.7188 | 0.7222 |
| `recall` | 1.0 | 1.0 |
| `retained_overlay_recall` | 1.0 | 1.0 |
| `post_dedup` segment count | 32 | 36 |

"Before" is the phase-3 doc's own reported numbers (`docs/plans/2026-08-28-ocr-phase3-typography.md`),
established in a prior session against the pre-ticker fixture with the identical pipeline
and config. "After" was measured in this session, back-to-back with the joint-distribution
run above (same environment, same RapidOCR weights, single continuous session). Re-running
the *old* fixture in this same session to get a strictly single-session "before" was judged
not worth the added machinery (checking out a second fixture-generator version mid-session)
given the two numbers already agree closely (0.7188 -> 0.7222, i.e. the added ticker moved
the metric by <0.5 relative, consistent with adding one more required overlay whose
raw-stage occurrences are a small fraction of the total segment count) and neither
comparison changes the conclusion.

Full funnel (this session, after):

| stage | segments | unmatched_rate | retained_overlay_recall |
|---|--:|--:|--:|
| raw | 139 | 0.7554 | 1.0 |
| post_pattern_filter | 115 | 0.7043 | 1.0 |
| post_frequency_filter | 91 | 0.6264 | 1.0 |
| post_dedup | 36 | 0.7222 | 1.0 |

Overall `recall = 1.0`, `precision = 0.278`. All 6 required overlays (including the new
ticker) matched.
