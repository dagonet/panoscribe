"""Junk-segment classification metrics for the OCR eval harness.

See ``docs/plans/2026-08-27-ocr-noise-measurement.md`` for the operational
definition of a junk segment and the rationale behind it. Summary:

A junk segment is a final-stage (or intermediate-stage) ``ON-SCREEN``/``BOTH``
segment that:

1. does not fuzzy-match (>= ``fuzzy_threshold``) any *individual*
   ground-truth expected text -- the same single-segment criterion
   :func:`panoscribe.eval.scoring.score_video` already uses for the
   false-positive side of precision, AND
2. has duration < ``max_duration_s``.

This intentionally does NOT use frame-appearance-count or spatial-instability
signals from the starting characterisation in the plan doc (short-lived, low
frame count, spatially unstable, not deliberate overlay). Those two signals
are not computable here: :class:`panoscribe.output.TranscriptSegment` carries
no per-frame provenance (no frame count, no bbox position) once it leaves
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
    """Junk-segment measurements for one stage of OCR output."""

    total_segments: int
    junk_count: int
    junk_rate: float
    retained_overlay_recall: float


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
    if expected.start is not None and segment.end < expected.start:
        return False
    if expected.end is not None and segment.start > expected.end:
        return False
    sim = fuzz.ratio(segment.text, expected.text, processor=str.lower) / 100.0
    return sim >= fuzzy_threshold


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

    SPEECH segments are never junk -- the definition is OCR-specific.
    """
    if segment.source not in _ON_SCREEN_SOURCES:
        return False
    duration = segment.end - segment.start
    if duration >= max_duration_s:
        return False
    return not is_matched_to_ground_truth(segment, ground_truth, fuzzy_threshold)


def compute_junk_metrics(
    segments: list[TranscriptSegment],
    ground_truth: GroundTruth,
    *,
    fuzzy_threshold: float,
    max_duration_s: float = DEFAULT_MAX_JUNK_DURATION_S,
) -> JunkMetrics:
    """Compute junk count/rate and retained-overlay recall for ``segments``.

    ``retained_overlay_recall`` is the fraction of *required* GT texts with
    at least one individually-matching segment in ``segments``. In the
    phase-1 synthetic fixture every GT entry is a deliberate overlay caption
    (the generated background paragraph text never appears in ground truth),
    so this equals standard recall restricted to single-segment matches (no
    pair/triple joining). It is reported as its own metric -- rather than
    reused from :func:`panoscribe.eval.scoring.score_video` -- so a
    junk-focused reduction that accidentally drops real overlay segments is
    visible here even on ground truth sets that later mix overlay and
    non-overlay required entries.
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

    required = [e for e in ground_truth.expected_texts if e.required]
    if required:
        matched_required = sum(
            1
            for expected in required
            if any(_matches_expected(seg, expected, fuzzy_threshold) for seg in segments)
        )
        retained_overlay_recall = matched_required / len(required)
    else:
        retained_overlay_recall = 1.0

    return JunkMetrics(
        total_segments=total,
        junk_count=junk_count,
        junk_rate=junk_rate,
        retained_overlay_recall=retained_overlay_recall,
    )
