"""Unit tests for panoscribe.ocr.bbox_aggregator.

``aggregate_frame_bboxes`` groups same-line RapidOCR bounding boxes into one
canonical caption per detected text region, in reading order. Pure helper —
no mocks required.
"""

from __future__ import annotations

import pytest

from panoscribe.ocr.bbox_aggregator import _reading_order, aggregate_frame_bboxes


def _box(x_min: float, y_min: float, x_max: float, y_max: float) -> list[tuple[float, float]]:
    """Build a 4-corner polygon in (x, y) order (axis-aligned rectangle)."""
    return [
        (x_min, y_min),
        (x_max, y_min),
        (x_max, y_max),
        (x_min, y_max),
    ]


def test_empty_input_returns_empty_output() -> None:
    assert aggregate_frame_bboxes([], [], [], min_confidence=0.6) == []


def test_single_bbox_returns_single_segment() -> None:
    boxes = [_box(0.0, 0.0, 100.0, 30.0)]
    out = aggregate_frame_bboxes(boxes, ["hello"], [0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].text == "hello"
    assert out[0].mean_conf == pytest.approx(0.9)


def test_two_bboxes_same_line_joined_left_to_right() -> None:
    # Both boxes on the same y-line (y_center = 15), x-adjacent.
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left
        _box(60.0, 0.0, 110.0, 30.0),  # right
    ]
    out = aggregate_frame_bboxes(boxes, ["left", "right"], [0.8, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].text == "left right"
    assert out[0].mean_conf == pytest.approx(0.85)


def test_two_bboxes_different_lines_yield_two_segments() -> None:
    # Top line y_center = 15, bottom line y_center = 100. Heights ~30 each →
    # tolerance = 15. Δ = 85 > 15 → separate lines.
    boxes = [
        _box(0.0, 0.0, 100.0, 30.0),  # top
        _box(0.0, 85.0, 100.0, 115.0),  # bottom
    ]
    out = aggregate_frame_bboxes(boxes, ["top", "bottom"], [0.9, 0.9], min_confidence=0.6)

    assert [line.text for line in out] == ["top", "bottom"]


def test_three_bboxes_one_line_out_of_x_order_sorts_by_x() -> None:
    # All on same y-line (y_center = 15). Provided in middle/right/left order;
    # output must be left → middle → right.
    boxes = [
        _box(60.0, 0.0, 100.0, 30.0),  # middle (x_center = 80)
        _box(120.0, 0.0, 160.0, 30.0),  # right  (x_center = 140)
        _box(0.0, 0.0, 40.0, 30.0),  # left   (x_center = 20)
    ]
    out = aggregate_frame_bboxes(
        boxes, ["middle", "right", "left"], [0.9, 0.9, 0.9], min_confidence=0.6
    )

    assert len(out) == 1
    assert out[0][0] == "left middle right"


def test_below_min_confidence_dropped_high_emits_alone() -> None:
    # Two bboxes on different y-lines. Below-threshold one disappears entirely.
    boxes = [
        _box(0.0, 0.0, 100.0, 30.0),  # keep
        _box(0.0, 100.0, 100.0, 130.0),  # drop (low score)
    ]
    out = aggregate_frame_bboxes(boxes, ["keep", "drop"], [0.9, 0.4], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "keep"


def test_mean_confidence_aggregation_on_one_line() -> None:
    # Three same-line bboxes; mean of (0.6, 0.9, 0.9) = 0.8.
    boxes = [
        _box(0.0, 0.0, 30.0, 30.0),
        _box(40.0, 0.0, 70.0, 30.0),
        _box(80.0, 0.0, 110.0, 30.0),
    ]
    out = aggregate_frame_bboxes(boxes, ["a", "b", "c"], [0.6, 0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].mean_conf == pytest.approx(0.8)


def test_tolerance_boundary_inclusive_merges() -> None:
    # mean_height = 30, tolerance = 15. Place second box's y_center at exactly
    # +15 from the first (delta == tolerance) — must merge by inclusive ``<=``.
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # y_center = 15
        _box(60.0, 15.0, 110.0, 45.0),  # y_center = 30 → Δ = 15 (boundary)
    ]
    out = aggregate_frame_bboxes(boxes, ["a", "b"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "a b"


def test_intra_frame_duplicate_text_emitted_once() -> None:
    # Same word detected twice (e.g. overlapping detections of "TRUE"); the
    # aggregator keeps the first and drops the second so the joined line
    # doesn't read "TRUE TRUE".
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # first "TRUE"
        _box(2.0, 1.0, 52.0, 31.0),  # near-duplicate detection of "TRUE"
    ]
    out = aggregate_frame_bboxes(boxes, ["TRUE", "TRUE"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "TRUE"


def test_length_mismatch_input_raises_assertion() -> None:
    boxes = [_box(0.0, 0.0, 50.0, 30.0)]
    texts: list[str] = ["a", "b"]
    scores: list[float] = [0.9]

    with pytest.raises(AssertionError, match="length mismatch"):
        aggregate_frame_bboxes(boxes, texts, scores, min_confidence=0.6)


def test_all_below_confidence_returns_empty() -> None:
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),
        _box(60.0, 0.0, 110.0, 30.0),
    ]
    out = aggregate_frame_bboxes(boxes, ["a", "b"], [0.3, 0.4], min_confidence=0.6)

    assert out == []


def test_three_separate_lines_emit_three_segments() -> None:
    # Three boxes stacked vertically, each its own line.
    boxes = [
        _box(0.0, 0.0, 100.0, 30.0),  # y_center = 15
        _box(0.0, 100.0, 100.0, 130.0),  # y_center = 115
        _box(0.0, 200.0, 100.0, 230.0),  # y_center = 215
    ]
    out = aggregate_frame_bboxes(
        boxes, ["top", "middle", "bottom"], [0.9, 0.9, 0.9], min_confidence=0.6
    )

    assert [line.text for line in out] == ["top", "middle", "bottom"]


def test_mixed_confidence_within_line_keeps_only_high_bbox() -> None:
    # Two bboxes on the same y-line; one below threshold. The line's joined
    # text and mean confidence reflect the surviving bbox only.
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # below threshold
        _box(60.0, 0.0, 110.0, 30.0),  # above threshold
    ]
    out = aggregate_frame_bboxes(boxes, ["lo", "hi"], [0.5, 0.8], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].text == "hi"
    assert out[0].mean_conf == pytest.approx(0.8)


# ── Sprint 9.3: Column-aware line splitting ────────────────────────────────


def test_column_gap_splits_line_into_two_segments() -> None:
    """Same y-line, gap 100 px with mean height 30 (ratio 3.3) -> 2 segments."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left column
        _box(150.0, 0.0, 200.0, 30.0),  # right column, gap=100, ratio≈3.3
    ]
    out = aggregate_frame_bboxes(boxes, ["Eier", "Nudeln"], [0.9, 0.8], min_confidence=0.6)

    assert len(out) == 2
    assert out[0][0] == "Eier"
    assert out[1][0] == "Nudeln"


def test_small_gap_stays_joined() -> None:
    """Same y-line, gap 10 px (0.33 x mean height) -> 1 joined segment."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left
        _box(60.0, 0.0, 110.0, 30.0),  # right, gap=10, ratio≈0.33
    ]
    out = aggregate_frame_bboxes(boxes, ["Hello", "World"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "Hello World"


def test_boundary_gap_at_threshold_stays_joined() -> None:
    """Gap exactly 2.0 x mean_height stays joined (strict >)."""
    # gap = 110 - 50 = 60, mean_height = 30, ratio = 2.0
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),
        _box(110.0, 0.0, 160.0, 30.0),
    ]
    out = aggregate_frame_bboxes(boxes, ["left", "right"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "left right"


def test_negative_gap_overlap_never_splits() -> None:
    """Overlapping x-ranges (negative gap) -> 1 segment."""
    boxes = [
        _box(0.0, 0.0, 100.0, 30.0),
        _box(50.0, 0.0, 150.0, 30.0),  # overlap: gap=50-100=-50
    ]
    out = aggregate_frame_bboxes(boxes, ["overlap", "text"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "overlap text"


def test_two_by_two_grid_emits_four_segments() -> None:
    """2 rows x 2 columns with gutter gaps -> 4 segments in row-major order."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # row 1, col 1
        _box(150.0, 0.0, 200.0, 30.0),  # row 1, col 2
        _box(0.0, 100.0, 50.0, 130.0),  # row 2, col 1
        _box(150.0, 100.0, 200.0, 130.0),  # row 2, col 2
    ]
    out = aggregate_frame_bboxes(
        boxes,
        ["r1c1", "r1c2", "r2c1", "r2c2"],
        [0.9, 0.9, 0.9, 0.9],
        min_confidence=0.6,
    )

    assert [line.text for line in out] == ["r1c1", "r1c2", "r2c1", "r2c2"]


def test_split_chunks_have_independent_mean_confidence() -> None:
    """2-column line: each chunk's confidence is the mean of that column's boxes only."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # col 1, score 0.6
        _box(60.0, 0.0, 110.0, 30.0),  # col 1, score 0.9
        _box(200.0, 0.0, 250.0, 30.0),  # col 2, score 0.7
        # gap between idx 1 and idx 2: 200-110=90, mean_height=30, ratio=3.0 > 2.0 -> split
    ]
    out = aggregate_frame_bboxes(boxes, ["A", "B", "C"], [0.6, 0.9, 0.7], min_confidence=0.6)

    assert len(out) == 2
    # col 1: "A B", mean (0.6+0.9)/2 = 0.75
    assert out[0][0] == "A B"
    assert out[0][1] == pytest.approx(0.75)
    # col 2: "C", confidence 0.7
    assert out[1][0] == "C"
    assert out[1][1] == pytest.approx(0.7)


def test_x_gap_tolerance_ratio_passthrough() -> None:
    """x_gap_tolerance_ratio=10.0 keeps a 3.3x gap joined."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left
        _box(150.0, 0.0, 200.0, 30.0),  # right, gap=100, ratio≈3.3
    ]
    out = aggregate_frame_bboxes(
        boxes,
        ["left", "right"],
        [0.9, 0.9],
        min_confidence=0.6,
        x_gap_tolerance_ratio=10.0,
    )

    assert len(out) == 1
    assert out[0][0] == "left right"


# ── Sprint 9.7: Position-aware intra-frame dedup ─────────────────────────────


def test_same_text_nested_box_deduped() -> None:
    """A fully-nested duplicate (RapidOCR double-detection) is still deduped."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # first detection
        _box(10.0, 5.0, 40.0, 25.0),  # nested inside the first
    ]
    out = aggregate_frame_bboxes(boxes, ["OK", "OK"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0][0] == "OK"


def test_same_text_cross_column_kept() -> None:
    """Same text in different columns is no longer silently dropped."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left column
        _box(150.0, 0.0, 200.0, 30.0),  # right column, same y-line, gap=100
    ]
    out = aggregate_frame_bboxes(boxes, ["Eier", "Eier"], [0.9, 0.9], min_confidence=0.6)

    # Gap 100 > 2.0 * mean_h 30 → split into 2 segments, both "Eier"
    assert len(out) == 2
    assert out[0][0] == "Eier"
    assert out[1][0] == "Eier"


def test_same_text_different_row_kept() -> None:
    """Same text on different rows is kept (fixes checklist-style repetitions)."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # top row
        _box(0.0, 100.0, 50.0, 130.0),  # bottom row, far enough apart in y
    ]
    out = aggregate_frame_bboxes(boxes, ["A", "A"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 2
    assert out[0][0] == "A"
    assert out[1][0] == "A"


def test_same_text_adjacent_non_overlapping_joined() -> None:
    """Adjacent same-text boxes that do not overlap are joined on one line."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # left
        _box(55.0, 0.0, 105.0, 30.0),  # right, 5px gap (0.17x mean_h < 2.0)
    ]
    out = aggregate_frame_bboxes(boxes, ["A", "A"], [0.9, 0.9], min_confidence=0.6)

    # Same line, gap below threshold → joined "A A"
    assert len(out) == 1
    assert out[0][0] == "A A"


# ── Phase 3: geometry plumbing (AggregatedLine) ──────────────────────────────


def test_single_bbox_geometry_matches_box_dimensions() -> None:
    """mean_box_height/y_center/x_center reflect the single survivor's geometry."""
    boxes = [_box(0.0, 10.0, 100.0, 40.0)]  # height=30, y_center=25, x_center=50
    out = aggregate_frame_bboxes(boxes, ["hello"], [0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].mean_box_height == pytest.approx(30.0)
    assert out[0].y_center == pytest.approx(25.0)
    assert out[0].x_center == pytest.approx(50.0)


def test_joined_line_geometry_is_averaged_over_chunk() -> None:
    """A 2-box joined chunk's geometry is the mean over both survivors."""
    boxes = [
        _box(0.0, 0.0, 50.0, 20.0),  # height=20, y_center=10, x_center=25
        _box(60.0, 0.0, 110.0, 40.0),  # height=40, y_center=20, x_center=85
    ]
    out = aggregate_frame_bboxes(boxes, ["left", "right"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 1
    assert out[0].mean_box_height == pytest.approx(30.0)
    assert out[0].y_center == pytest.approx(15.0)
    assert out[0].x_center == pytest.approx(55.0)


def test_column_split_chunks_have_independent_geometry() -> None:
    """Each column-split chunk carries its own geometry, not the whole line's."""
    boxes = [
        _box(0.0, 0.0, 50.0, 30.0),  # col 1, height=30
        _box(200.0, 0.0, 250.0, 50.0),  # col 2, height=50, gap=150 -> split
    ]
    out = aggregate_frame_bboxes(boxes, ["A", "B"], [0.9, 0.9], min_confidence=0.6)

    assert len(out) == 2
    assert out[0].mean_box_height == pytest.approx(30.0)
    assert out[1].mean_box_height == pytest.approx(50.0)


# --- right-to-left reading order (#188) ---------------------------------------
#
# Texts below are written in LEFT-TO-RIGHT screen order, i.e. the order the
# aggregator receives them after sorting by x. The recogniser returns each box's
# text in logical order.


def _row_text(texts_left_to_right: list[str]) -> str:
    boxes = [_box(i * 50.0, 0.0, i * 50.0 + 40.0, 30.0) for i in range(len(texts_left_to_right))]
    out = aggregate_frame_bboxes(
        boxes, texts_left_to_right, [0.9] * len(texts_left_to_right), min_confidence=0.6
    )
    assert len(out) == 1
    return out[0].text


@pytest.mark.parametrize(
    ("screen_order", "expected"),
    [
        (["بالعالم", "مرحبا"], "مرحبا بالعالم"),
        (["دولار", "123", "سعر"], "سعر 123 دولار"),
        (["بالعالم", "2026", "مرحبا"], "مرحبا 2026 بالعالم"),
        (["AI", "Model", "2024", "عربي"], "عربي AI Model 2024"),
        (["שלום", "עולם"], "עולם שלום"),
        # Arabic-Indic digits are not part of the Latin phrase next to them.
        (["Model", "١٢٣", "AI", "عربي"], "عربي AI ١٢٣ Model"),
        # A mainly-Latin line with Arabic inside keeps its word order.
        (["Welcome", "مرحبا", "to", "the", "show"], "Welcome مرحبا to the show"),
        (["Price", "سعر", "is", "10"], "Price سعر is 10"),
        (["Hello", "بالعالم", "مرحبا", "today"], "Hello مرحبا بالعالم today"),
        (["Hello", "2026", "مرحبا", "world"], "Hello مرحبا 2026 world"),
        # Latin, digits and CJK keep today's left-to-right join.
        (["left", "right"], "left right"),
        (["2026", "123"], "2026 123"),
        (["你好", "世界", "2026"], "你好 世界 2026"),
    ],
)
def test_rtl_boxes_are_read_right_to_left_and_others_left_to_right(
    screen_order: list[str], expected: str
) -> None:
    assert _row_text(screen_order) == expected


@pytest.mark.parametrize(
    ("screen_order", "expected"),
    [
        ([], []),
        (["a", "b", "c"], ["a", "b", "c"]),
        (["1", "2"], ["1", "2"]),
        (["ب", "أ"], ["أ", "ب"]),
        (["Hello", "World", "ب", "أ"], ["أ", "ب", "Hello", "World"]),
        # Digit-only boxes between Arabic boxes stay single units (no re-reversal).
        (["ج", "2", "1", "ب"], ["ب", "1", "2", "ج"]),
        # Two separate Latin phrases, each kept left to right.
        (["B1", "B2", "ج", "A1", "A2", "ب"], ["ب", "A1", "A2", "ج", "B1", "B2"]),
        # Punctuation-only boxes at the edge of a Latin run keep their right-to-left place.
        ([":", "AI", "عربي"], ["عربي", "AI", ":"]),
        (["ب", "!", "AI", "عربي"], ["عربي", "AI", "!", "ب"]),
        ([":", "AI", "2024", "عربي"], ["عربي", "AI", "2024", ":"]),
        # Arabic-Indic digits are separators like Arabic words, not part of the Latin run.
        (["١٢٣", "AI", "عربي"], ["عربي", "AI", "١٢٣"]),
        (["Model", "١٢٣", "AI", "عربي"], ["عربي", "AI", "١٢٣", "Model"]),
        # A line whose outer letter boxes are Latin is a left-to-right line: Arabic boxes
        # keep their place, and a run of Arabic boxes is reversed.
        (["Welcome", "مرحبا", "to", "the", "show"], ["Welcome", "مرحبا", "to", "the", "show"]),
        (["Price", "سعر", "is", "10"], ["Price", "سعر", "is", "10"]),
        (["Hello", "بالعالم", "مرحبا", "today"], ["Hello", "مرحبا", "بالعالم", "today"]),
        # Numbers after an Arabic word are shown left of it; they read after it.
        (["Hello", "2026", "مرحبا", "world"], ["Hello", "مرحبا", "2026", "world"]),
        (["Hello", "2027", "2026", "مرحبا", "world"], ["Hello", "مرحبا", "2026", "2027", "world"]),
        # A number between two Arabic boxes joins their run.
        (
            ["Hello", "بالعالم", "2026", "مرحبا", "today"],
            ["Hello", "مرحبا", "2026", "بالعالم", "today"],
        ),
        # An Arabic-Indic number right of an Arabic word is drawn on its left (the bidi
        # algorithm lays the number out right to left), so it reads before the word.
        (["Hello", "مرحبا", "١٢٣", "today"], ["Hello", "١٢٣", "مرحبا", "today"]),
        (["Hello", "مرحبا", "!", "١٢٣", "today"], ["Hello", "١٢٣", "!", "مرحبا", "today"]),
        # Only Arabic-Indic digits (class AN) extend the run to the right: a Western digit
        # box there is left alone.
        (["Hello", "مرحبا", "2026", "today"], ["Hello", "مرحبا", "2026", "today"]),
        # Trailing punctuation and separate Arabic words keep their place.
        (["Hello", "مرحبا", "today", "!"], ["Hello", "مرحبا", "today", "!"]),
        (["Hello", "مرحبا", "today", "سعر", "Bye"], ["Hello", "مرحبا", "today", "سعر", "Bye"]),
        # Documented limits (box texts alone cannot tell these apart):
        # a number directly followed by a Latin word in an Arabic line,
        (["AI", "2024", "عربي"], ["عربي", "AI", "2024"]),
        # several numbers in a row before a Latin word in an Arabic line,
        (["AI", "2025", "2024", "عربي"], ["عربي", "AI", "2025", "2024"]),
        # a left-to-right line whose last word is Arabic reads as right-to-left (the same
        # screen as the Arabic line above),
        (["Hello", "2026", "مرحبا"], ["مرحبا", "Hello", "2026"]),
        (["Hello", "بالعالم", "مرحبا"], ["مرحبا", "بالعالم", "Hello"]),
        # a number before an Arabic word in a left-to-right line reads after it,
        (["Hello", "2026", "مرحبا", "today"], ["Hello", "مرحبا", "2026", "today"]),
        # and an Arabic line with a Latin word at both ends reads as left-to-right.
        (["Model", "عربي", "AI"], ["Model", "عربي", "AI"]),
    ],
)
def test_reading_order_helper(screen_order: list[str], expected: list[str]) -> None:
    assert _reading_order(screen_order) == expected
