"""Per-frame bounding-box aggregation for RapidOCR results.

Groups same-line bboxes into a single canonical caption string per text
region per frame, *before* cross-frame deduplication runs. RapidOCR returns
text at the word/region level; without this stage a visible caption like
``KEINE KAMPFSPORTTECHNIK KEINE`` produces three separate point segments per
frame and downstream text-similarity dedup never clusters them.

Pure function — no side effects, no I/O, no logging. Caller is responsible
for confidence-threshold semantics (passed in as ``min_confidence``).

Algorithm (per frame):
    1. Drop bboxes whose individual ``score < min_confidence``.
    2. Drop intra-frame duplicate-text bboxes (overlapping detections of
       the same word) — keep first occurrence.
    3. Compute axis-aligned ``y_min``/``y_max``/``x_min``/``x_max`` from each
       polygon's four corners; derive ``y_center``, ``x_center``, ``box_height``.
    4. Compute frame-wide ``mean_height`` over surviving boxes; this is the
       tolerance baseline for line grouping (more robust than per-line running
       mean, which is fragile if the first bbox is a tiny icon).
    5. Sort by ``y_center``; walk the list joining boxes whose
       ``abs(y_center - line.y_center_running_mean) <= 0.5 * mean_height``
       to the current line, otherwise start a new line. ``<=`` is inclusive —
       a delta exactly equal to the tolerance joins the current line.
    6. Within each line, sort by ``x_center`` for left-to-right reading order.
    7. Emit one :class:`AggregatedLine` per line, carrying joined text, mean
       confidence, and line geometry (``mean_box_height``, ``y_center``,
       ``x_center``) for internal (non-schema) diagnostics -- see
       ``docs/plans/2026-08-28-ocr-phase3-typography.md``.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Sequence


def _has_bidi_class(text: str, classes: frozenset[str]) -> bool:
    return any(unicodedata.bidirectional(ch) in classes for ch in text)


_RTL_CLASSES = frozenset({"R", "AL"})
_LTR_CLASSES = frozenset({"L"})
_LETTER_CLASSES = frozenset({"L", "R", "AL"})
# Boxes that end a left-to-right run inside a right-to-left line: Arabic words and
# Arabic-Indic digits (class AN), which the bidi algorithm lays out right to left.
_SEPARATOR_CLASSES = frozenset({"R", "AL", "AN"})
_NUMBER_CLASSES = frozenset({"EN", "AN"})
_RUN_EDGE_CLASSES = frozenset({"L", "EN"})


def _is_ltr_line(texts: list[str]) -> bool:
    """True when the leftmost and rightmost boxes that hold a letter are both Latin-only."""
    letter_boxes = [t for t in texts if _has_bidi_class(t, _LETTER_CLASSES)]
    return all(
        _has_bidi_class(t, _LTR_CLASSES) and not _has_bidi_class(t, _RTL_CLASSES)
        for t in (letter_boxes[0], letter_boxes[-1])
    )


def _ltr_line_order(texts: list[str]) -> list[str]:
    """Order a left-to-right line that has Arabic/Hebrew boxes inside it.

    The boxes keep their screen order, except that each run of right-to-left boxes is
    reversed (the bidi algorithm shows such a run mirrored). A digit or punctuation box
    between two boxes of a run belongs to it, and so do digit boxes directly to the left
    of it, because a number that follows a right-to-left word is drawn on its left.
    """
    rtl = [i for i, t in enumerate(texts) if _has_bidi_class(t, _RTL_CLASSES)]
    runs: list[list[int]] = []
    for index in rtl:
        gap = texts[runs[-1][-1] + 1 : index] if runs else None
        if gap is not None and not any(_has_bidi_class(t, _LETTER_CLASSES) for t in gap):
            runs[-1].append(index)
        else:
            runs.append([index])

    ordered = list(texts)
    for run in runs:
        start = run[0]
        k = start - 1
        while k >= 0 and not _has_bidi_class(texts[k], _LETTER_CLASSES):
            if _has_bidi_class(texts[k], _NUMBER_CLASSES):
                start = k
            k -= 1
        end = run[-1] + 1
        ordered[start:end] = ordered[start:end][::-1]
    return ordered


def _rtl_line_order(texts: list[str]) -> list[str]:
    """Order a right-to-left line: boxes right to left, Latin phrases kept left to right."""
    ordered: list[str] = []
    run: list[str] = []

    def flush() -> None:
        # Only a run with a Latin letter is put back left to right, and only from its first
        # to its last Latin/number box: punctuation boxes at the ends keep their place.
        if any(_has_bidi_class(t, _LTR_CLASSES) for t in run):
            edges = [i for i, t in enumerate(run) if _has_bidi_class(t, _RUN_EDGE_CLASSES)]
            first, last = edges[0], edges[-1]
            run[first : last + 1] = run[first : last + 1][::-1]
        ordered.extend(run)
        run.clear()

    for text in texts[::-1]:
        if _has_bidi_class(text, _SEPARATOR_CLASSES):
            flush()
            ordered.append(text)
        else:
            run.append(text)
    flush()
    return ordered


def _reading_order(texts: list[str]) -> list[str]:
    """Order one line's box texts (given left to right on screen) for reading.

    Lines without a right-to-left character (Arabic, Hebrew) come back unchanged, so
    Latin, CJK and digit-only lines are never touched. A line with one is read in one of
    two ways, chosen from the boxes alone:

    * Left-to-right line: the leftmost and the rightmost box that contains a letter are
      both Latin-only (``Welcome مرحبا to the show``). The boxes keep their screen order and
      each run of right-to-left boxes is reversed (see :func:`_ltr_line_order`).
    * Otherwise a right-to-left paragraph: the box sequence is reversed, then each maximal
      run of boxes between Arabic words or Arabic-Indic digits that holds a Latin letter
      (``AI Model 2024``) is put back left to right, from its first to its last Latin or
      number box (see :func:`_rtl_line_order`).

    Each box's own text is already in logical order (the recogniser output is not
    re-ordered, see ``rapid_ocr._keep_logical_text_order``), so it is never touched here.

    Known limits, because the boxes alone cannot tell these cases apart:

    * Inside an Arabic line, a number followed by a Latin word swaps places:
      ``عربي 2024 AI`` comes out as ``عربي AI 2024``, and several numbers in a row before a
      Latin word (``عربي 2024 2025 AI``) come out as ``عربي AI 2025 2024``.
    * A Latin line that ends in Arabic looks like an Arabic line that ends in Latin, so it
      is read as Arabic: ``Hello مرحبا 2026`` comes out as ``مرحبا Hello 2026``. For the same
      reason ``Hello 2026 مرحبا today`` comes out as ``Hello مرحبا 2026 today``.
    * In a Latin line, an Arabic-Indic number before an Arabic word is drawn on its right
      and reads after it: ``Hello ١٢٣ مرحبا today`` comes out as ``Hello مرحبا ١٢٣ today``.
    * An Arabic line with a Latin word at both ends (``AI عربي Model``) is read as a Latin
      line, so the two Latin words and the Arabic word come out in screen order.
    """
    if not any(_has_bidi_class(t, _RTL_CLASSES) for t in texts):
        return texts
    if _is_ltr_line(texts):
        return _ltr_line_order(texts)
    return _rtl_line_order(texts)


class AggregatedLine(NamedTuple):
    """One aggregated text line/chunk plus its geometry.

    Internal to the OCR pipeline -- never serialized. ``mean_box_height`` /
    ``y_center`` / ``x_center`` are averages over the surviving bboxes that
    make up this line/chunk, in the same pixel coordinate space as the input
    ``boxes``. Callers wanting a scale-invariant height should divide
    ``mean_box_height`` by the frame height themselves (safe because
    :func:`panoscribe.ocr.preprocessor.preprocess` never resizes).
    """

    text: str
    mean_conf: float
    mean_box_height: float
    y_center: float
    x_center: float


class _Survivor(NamedTuple):
    """A single bbox that passed the confidence + dedup filters.

    Internal helper — keeps the line-grouping loop readable and prevents the
    positional-tuple drift that bit Sprint OCR-Recall's first round of code
    review (a stale ``score`` slot left over from a refactor).
    """

    y_center: float
    x_center: float
    box_height: float
    x_min: float
    x_max: float
    text: str
    score: float


def _overlaps(
    survivor: _Survivor,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> bool:
    """True if survivor's bbox spatially overlaps the incoming box on BOTH axes.

    Strict ``<`` comparison — touching boxes with zero intersection area are
    NOT considered duplicates (correct for RapidOCR double-detections that
    produce near-identical boxes).
    """
    top = survivor.y_center - survivor.box_height / 2.0
    bottom = survivor.y_center + survivor.box_height / 2.0
    x_overlap = survivor.x_min < x_max and x_min < survivor.x_max
    y_overlap = top < y_max and y_min < bottom
    return x_overlap and y_overlap


def aggregate_frame_bboxes(
    boxes: Sequence[Sequence[tuple[float, float]]],
    texts: Sequence[str],
    scores: Sequence[float],
    *,
    min_confidence: float,
    y_tolerance_ratio: float = 0.5,
    x_gap_tolerance_ratio: float = 2.0,
) -> list[AggregatedLine]:
    """Group bboxes into reading-order lines, splitting on column gaps.

    Parameters
    ----------
    boxes:
        Sequence of 4-corner polygons; each polygon is a sequence of four
        ``(x, y)`` tuples (RapidOCR's rotated-rectangle output, used here as
        an axis-aligned bounding rectangle for grouping).
    texts:
        Per-bbox text strings; ``len(texts) == len(boxes)``.
    scores:
        Per-bbox confidence scores in ``[0.0, 1.0]``; ``len(scores) == len(boxes)``.
    min_confidence:
        Bboxes with ``score < min_confidence`` are dropped *before* grouping
        (mirrors the per-bbox confidence semantics of the pre-aggregation
        loop). A line never inherits a low-confidence word.
    y_tolerance_ratio:
        Multiplier on ``frame_mean_height`` used as the y-delta tolerance
        for joining a bbox to the current line. Default ``0.5`` means a
        bbox joins if its ``y_center`` is within half the mean line height
        of the running line center.
    x_gap_tolerance_ratio:
        Multiplier on ``frame_mean_height`` used as the x-gap threshold
        for splitting a same-y-line group into separate column chunks.
        Word/phrase gaps are typically 0.2-0.6x text height; column gutters
        are 3-5x. Default ``2.0`` keeps word gaps joined while splitting
        column gutters. Strict ``>`` — a gap exactly at threshold stays
        joined. Negative gaps (overlapping boxes) never split.

    Returns
    -------
    list[AggregatedLine]
        One :class:`AggregatedLine` per detected text chunk, in top-to-bottom,
        left-to-right reading order. Within each line, words with gap >
        ``x_gap_tolerance_ratio * mean_height`` produce separate chunks.
        Empty input returns an empty list.

    Raises
    ------
    AssertionError
        If ``len(boxes) != len(texts)`` or ``len(boxes) != len(scores)`` —
        this is a RapidOCR contract violation; failing fast here is safer
        than silently truncating to the shortest sequence.
    """
    assert len(boxes) == len(texts) == len(scores), (
        f"length mismatch: boxes={len(boxes)}, texts={len(texts)}, scores={len(scores)}"
    )
    # Use ``len`` rather than truthiness — RapidOCR returns ``boxes`` as a
    # numpy array, where ``if not boxes:`` raises ``ValueError``.
    if len(boxes) == 0:
        return []

    # Steps 1+2+3: confidence filter, intra-frame spatial dedup, axis-aligned geometry.
    survivors: list[_Survivor] = []
    seen: dict[str, list[_Survivor]] = {}
    for box, text, score in zip(boxes, texts, scores, strict=True):
        if score < min_confidence:
            continue
        # Step 3: derive axis-aligned bounding rectangle from the polygon
        # (computed before dedup because spatial overlap needs geometry).
        ys = [pt[1] for pt in box]
        xs = [pt[0] for pt in box]
        y_min, y_max = min(ys), max(ys)
        x_min, x_max = min(xs), max(xs)

        # Step 2: spatial dedup — skip if any accepted same-text box overlaps
        # this one on both axes. Same text in another column or row is kept
        # (non-overlapping same-text repetitions are legitimate); overlapping
        # double-detections (RapidOCR's most common dup pattern) are dropped.
        if text in seen:
            is_dup = False
            for survivor in seen[text]:
                if _overlaps(survivor, x_min, x_max, y_min, y_max):
                    is_dup = True
                    break
            if is_dup:
                continue

        survivor = _Survivor(
            y_center=(y_min + y_max) / 2.0,
            x_center=(x_min + x_max) / 2.0,
            box_height=y_max - y_min,
            x_min=x_min,
            x_max=x_max,
            text=text,
            score=float(score),
        )
        survivors.append(survivor)
        seen.setdefault(text, []).append(survivor)

    if not survivors:
        return []

    # Step 4: frame-wide mean height as the tolerance baseline.
    mean_height = sum(s.box_height for s in survivors) / len(survivors)
    tolerance = y_tolerance_ratio * mean_height

    # Step 5: sort by y_center, walk into lines.
    survivors.sort(key=lambda s: s.y_center)
    lines: list[list[_Survivor]] = []
    line_centers: list[float] = []  # running mean y_center per line
    for entry in survivors:
        if not lines:
            lines.append([entry])
            line_centers.append(entry.y_center)
            continue
        last_center = line_centers[-1]
        if abs(entry.y_center - last_center) <= tolerance:
            lines[-1].append(entry)
            # Update running mean for the current line.
            n = len(lines[-1])
            line_centers[-1] = ((last_center * (n - 1)) + entry.y_center) / n
        else:
            lines.append([entry])
            line_centers.append(entry.y_center)

    # Steps 6+7: within each line sort by x_center, then split on column gaps.
    out: list[AggregatedLine] = []
    for line in lines:
        line.sort(key=lambda s: s.x_center)
        # Split the line into chunks where adjacent x-gap exceeds threshold.
        chunks: list[list[_Survivor]] = []
        current = [line[0]]
        for nxt in line[1:]:
            gap = nxt.x_min - current[-1].x_max
            if gap > x_gap_tolerance_ratio * mean_height:
                chunks.append(current)
                current = []
            current.append(nxt)
        chunks.append(current)
        # Each chunk emits its own joined text, mean confidence, and geometry
        # (averaged over the chunk's surviving bboxes).
        for chunk in chunks:
            joined_text = " ".join(_reading_order([s.text for s in chunk]))
            mean_conf = sum(s.score for s in chunk) / len(chunk)
            chunk_mean_height = sum(s.box_height for s in chunk) / len(chunk)
            chunk_y_center = sum(s.y_center for s in chunk) / len(chunk)
            chunk_x_center = sum(s.x_center for s in chunk) / len(chunk)
            out.append(
                AggregatedLine(
                    text=joined_text,
                    mean_conf=mean_conf,
                    mean_box_height=chunk_mean_height,
                    y_center=chunk_y_center,
                    x_center=chunk_x_center,
                )
            )
    return out
