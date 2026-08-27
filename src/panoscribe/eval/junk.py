"""Junk-segment classification metrics for the OCR eval harness.

See ``docs/plans/2026-08-27-ocr-noise-measurement.md`` (phase 1) and
``docs/plans/2026-08-27-ocr-phase2-stability.md`` (phase 2, this module's
current shape) for the operational definitions and their history.

**Authoritative metric: ``unmatched_rate`` / :func:`is_unmatched_segment`.**
A segment is unmatched if it is ON-SCREEN/BOTH and does not fuzzy-match
(>= ``fuzzy_threshold``) any *individual* ground-truth expected text -- the
same single-segment criterion :func:`panoscribe.eval.scoring.score_video`
uses for the false-positive side of precision. There is no duration
exemption: phase 1's ``is_junk_segment`` exempted segments with
``duration >= 1.5s`` on the theory that a merged multi-frame span could not
be a single-frame survivor, but that exemption is inert in video mode
(``extract()`` sets ``start == end``, duration always 0) and only reachable
in images mode -- meaning the *same* unmatched segment was scored
differently depending on extraction mode. ``is_junk_segment`` /
``JunkMetrics.junk_rate`` are kept below for continuity with phase-1
baselines but are NOT the metric any materiality bar should be set against;
use ``unmatched_count`` / ``unmatched_rate``.

This intentionally does NOT use frame-appearance-count or spatial-instability
signals from the phase-1 starting characterisation (short-lived, low frame
count, spatially unstable, not deliberate overlay). Those two signals are
not computable here: :class:`panoscribe.output.TranscriptSegment` carries no
per-frame provenance (no frame count, no bbox position) once it leaves
:func:`panoscribe.ocr.bbox_aggregator.aggregate_frame_bboxes`. That gap is
itself a phase-1 finding -- see the plan doc's "Findings" section.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from panoscribe.eval.models import ExpectedText, GroundTruth
    from panoscribe.output import TranscriptSegment

#: Default junk-duration ceiling in seconds. One image-mode "frame" spans
#: exactly 1.0s (see ``RapidOCREngine.extract_images``); a segment shorter
#: than a single merged multi-frame span is a single-frame survivor by
#: construction.
DEFAULT_MAX_JUNK_DURATION_S: float = 1.5

_ON_SCREEN_SOURCES = ("ON-SCREEN", "BOTH")


@dataclass(frozen=True)
class JunkMetrics:
    """Junk-segment measurements for one stage of OCR output.

    ``unmatched_count``/``unmatched_rate`` are the authoritative,
    mode-independent metric (see module docstring). ``junk_count``/
    ``junk_rate`` are the phase-1 definition (duration-exempt), kept only
    for continuity with the phase-1 baseline.
    """

    total_segments: int
    junk_count: int
    junk_rate: float
    unmatched_count: int
    unmatched_rate: float
    retained_overlay_recall: float


def _within_window(
    segment: TranscriptSegment,
    start: float | None,
    end: float | None,
) -> bool:
    """True if ``segment``'s span overlaps ``[start, end]`` (either bound optional)."""
    if start is not None and segment.end < start:
        return False
    return not (end is not None and segment.start > end)


def _text_matches(segment: TranscriptSegment, text: str, fuzzy_threshold: float) -> bool:
    sim = fuzz.ratio(segment.text, text, processor=str.lower) / 100.0
    return sim >= fuzzy_threshold


def _matches_expected(
    segment: TranscriptSegment,
    expected: ExpectedText,
    fuzzy_threshold: float,
) -> bool:
    """True if ``segment`` fuzzy-matches a single ``ExpectedText`` entry.

    Single-segment only (no pair/triple joining) -- mirrors the
    single-segment pass in
    ``panoscribe.eval.scoring._build_similarity_lookup``. Respects the GT
    entry's optional time window.
    """
    if not _within_window(segment, expected.start, expected.end):
        return False
    return _text_matches(segment, expected.text, fuzzy_threshold)


def is_matched_to_ground_truth(
    segment: TranscriptSegment,
    ground_truth: GroundTruth,
    fuzzy_threshold: float,
) -> bool:
    """True if ``segment`` fuzzy-matches at least one GT expected text.

    Deliberately duplicated (not imported) from
    ``panoscribe.eval.scoring``: that module keeps its per-segment matcher
    private, and re-deriving the ~10-line check here avoids widening
    scoring.py's public surface for a measurement-only consumer.
    """
    return any(
        _matches_expected(segment, expected, fuzzy_threshold)
        for expected in ground_truth.expected_texts
    )


def is_junk_segment(
    segment: TranscriptSegment,
    ground_truth: GroundTruth,
    *,
    fuzzy_threshold: float,
    max_duration_s: float = DEFAULT_MAX_JUNK_DURATION_S,
) -> bool:
    """True if ``segment`` meets the phase-1 junk-segment definition.

    DEPRECATED as the authoritative metric -- see the module docstring and
    :func:`is_unmatched_segment`. The ``duration >= max_duration_s``
    exemption below is inert in video mode (``RapidOCREngine.extract``
    always sets ``start == end``) and only reachable in images mode, so this
    predicate scores the *same* unmatched segment differently depending on
    extraction mode. Kept only so phase-1 baselines remain reproducible.

    SPEECH segments are never junk -- the definition is OCR-specific.
    """
    if segment.source not in _ON_SCREEN_SOURCES:
        return False
    duration = segment.end - segment.start
    if duration >= max_duration_s:
        return False
    return not is_matched_to_ground_truth(segment, ground_truth, fuzzy_threshold)


def is_unmatched_segment(
    segment: TranscriptSegment,
    ground_truth: GroundTruth,
    *,
    fuzzy_threshold: float,
) -> bool:
    """True if ``segment`` is ON-SCREEN/BOTH and matches no GT expected text.

    This is the authoritative, mode-independent noise definition -- no
    duration exemption, so a merged multi-frame cluster that never matches
    ground truth still counts as noise (the case phase 1's duration
    exemption was hiding in images mode). SPEECH segments are never
    unmatched-as-noise -- the definition is OCR-specific.
    """
    if segment.source not in _ON_SCREEN_SOURCES:
        return False
    return not is_matched_to_ground_truth(segment, ground_truth, fuzzy_threshold)


def _retained_overlay_recall(
    segments: list[TranscriptSegment],
    ground_truth: GroundTruth,
    fuzzy_threshold: float,
) -> float:
    """Fraction of required GT appearances with a matching segment.

    For each required :class:`ExpectedText`:

    * If it declares ``appearances`` (a list of ``(start, end)`` windows),
      each appearance is scored independently -- a segment must fuzzy-match
      the text AND overlap that specific window. This makes PARTIAL loss of
      a recurring overlay visible (e.g. 8 of 10 appearances matched ->
      0.8), unlike the coarse ``>= 1 match anywhere`` check, which is
      pinned at 1.0 as soon as a single appearance survives.
    * Otherwise, falls back to the phase-1 behaviour: >= 1 matching segment
      anywhere in ``[start, end]`` (or unbounded if unset) counts as 1/1.
      This keeps existing ground-truth files (real ``eval``-marked samples
      included) scoring identically -- ``appearances`` is additive, not a
      breaking schema change.

    Denominator is total appearances (or total required entries when none
    declare ``appearances``); 1.0 when there are no required entries.
    """
    required = [e for e in ground_truth.expected_texts if e.required]
    if not required:
        return 1.0

    matched = 0
    total = 0
    for expected in required:
        if expected.appearances:
            for start, end in expected.appearances:
                total += 1
                if any(
                    _within_window(seg, start, end)
                    and _text_matches(seg, expected.text, fuzzy_threshold)
                    for seg in segments
                ):
                    matched += 1
        else:
            total += 1
            if any(_matches_expected(seg, expected, fuzzy_threshold) for seg in segments):
                matched += 1
    return matched / total if total > 0 else 1.0


def compute_junk_metrics(
    segments: list[TranscriptSegment],
    ground_truth: GroundTruth,
    *,
    fuzzy_threshold: float,
    max_duration_s: float = DEFAULT_MAX_JUNK_DURATION_S,
) -> JunkMetrics:
    """Compute noise/junk counts and retained-overlay recall for ``segments``.

    ``unmatched_count``/``unmatched_rate`` are the authoritative metric (see
    module docstring); ``junk_count``/``junk_rate`` are kept for phase-1
    baseline continuity only.

    ``retained_overlay_recall`` -- see :func:`_retained_overlay_recall`.
    Reported as its own metric (rather than reused from
    :func:`panoscribe.eval.scoring.score_video`) so a noise-focused
    reduction that accidentally drops real overlay segments is visible
    here.

    Note: computed against whichever stage's ``segments`` are passed in.
    Post-dedup segments have already been merged across frames (dedup's
    ``gap_tolerance`` bridges short gaps), so a per-appearance hole *inside*
    a merged span is invisible at that stage -- per-appearance recall is
    most sensitive at ``raw``/``post_pattern_filter``/``post_frequency_filter``,
    before dedup has a chance to paper over a gap.
    """
    on_screen = [s for s in segments if s.source in _ON_SCREEN_SOURCES]
    total = len(on_screen)
    junk_count = sum(
        1
        for seg in on_screen
        if is_junk_segment(
            seg,
            ground_truth,
            fuzzy_threshold=fuzzy_threshold,
            max_duration_s=max_duration_s,
        )
    )
    junk_rate = junk_count / total if total > 0 else 0.0

    unmatched_count = sum(
        1
        for seg in on_screen
        if is_unmatched_segment(seg, ground_truth, fuzzy_threshold=fuzzy_threshold)
    )
    unmatched_rate = unmatched_count / total if total > 0 else 0.0

    retained_overlay_recall = _retained_overlay_recall(segments, ground_truth, fuzzy_threshold)

    return JunkMetrics(
        total_segments=total,
        junk_count=junk_count,
        junk_rate=junk_rate,
        unmatched_count=unmatched_count,
        unmatched_rate=unmatched_rate,
        retained_overlay_recall=retained_overlay_recall,
    )
