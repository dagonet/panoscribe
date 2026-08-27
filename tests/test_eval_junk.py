"""Unit tests for panoscribe.eval.junk.

CI-safe: no GPU, no external dependencies beyond Python + rapidfuzz.
"""

from __future__ import annotations

from panoscribe.eval.junk import (
    DEFAULT_MAX_JUNK_DURATION_S,
    compute_junk_metrics,
    is_junk_segment,
    is_matched_to_ground_truth,
)
from panoscribe.eval.models import ExpectedText, GroundTruth
from panoscribe.output import TranscriptSegment


def _seg(
    text: str,
    start: float = 0.0,
    end: float | None = None,
    source: str = "ON-SCREEN",
) -> TranscriptSegment:
    return TranscriptSegment(
        start=start,
        end=end if end is not None else start,
        text=text,
        source=source,
    )


def _gt(texts: list[tuple[str, bool]]) -> GroundTruth:
    return GroundTruth(
        language="en",
        expected_texts=[ExpectedText(text=t, required=r) for t, r in texts],
    )


class TestIsMatchedToGroundTruth:
    def test_exact_match_true(self) -> None:
        seg = _seg("Hello World")
        gt = _gt([("Hello World", True)])
        assert is_matched_to_ground_truth(seg, gt, fuzzy_threshold=0.85) is True

    def test_no_match_false(self) -> None:
        seg = _seg("Completely unrelated text")
        gt = _gt([("Hello World", True)])
        assert is_matched_to_ground_truth(seg, gt, fuzzy_threshold=0.85) is False

    def test_time_window_excludes_segment_after_end(self) -> None:
        seg = _seg("Hello World", start=100.0, end=100.0)
        gt = GroundTruth(
            language="en",
            expected_texts=[ExpectedText(text="Hello World", start=0.0, end=5.0)],
        )
        assert is_matched_to_ground_truth(seg, gt, fuzzy_threshold=0.85) is False

    def test_time_window_excludes_segment_before_start(self) -> None:
        seg = _seg("Hello World", start=0.0, end=0.0)
        gt = GroundTruth(
            language="en",
            expected_texts=[ExpectedText(text="Hello World", start=50.0, end=55.0)],
        )
        assert is_matched_to_ground_truth(seg, gt, fuzzy_threshold=0.85) is False


class TestIsJunkSegment:
    def test_short_unmatched_on_screen_is_junk(self) -> None:
        seg = _seg("Random background text", start=3.0, end=4.0)
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        assert is_junk_segment(seg, gt, fuzzy_threshold=0.85) is True

    def test_matched_segment_is_never_junk_even_if_short(self) -> None:
        seg = _seg("SEASON FINALE LIVE NOW", start=3.0, end=4.0)
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        assert is_junk_segment(seg, gt, fuzzy_threshold=0.85) is False

    def test_long_unmatched_segment_is_not_junk(self) -> None:
        seg = _seg("Random background text", start=0.0, end=10.0)
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        assert is_junk_segment(seg, gt, fuzzy_threshold=0.85) is False

    def test_speech_segment_is_never_junk(self) -> None:
        seg = _seg("Random background text", start=3.0, end=4.0, source="SPEECH")
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        assert is_junk_segment(seg, gt, fuzzy_threshold=0.85) is False

    def test_duration_boundary_is_exclusive(self) -> None:
        seg = _seg(
            "Random background text",
            start=0.0,
            end=DEFAULT_MAX_JUNK_DURATION_S,
        )
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        # duration == max_duration_s is NOT < max_duration_s -- not junk.
        assert is_junk_segment(seg, gt, fuzzy_threshold=0.85) is False


class TestComputeJunkMetrics:
    def test_hand_computed_mixed_case(self) -> None:
        """Hand-computed precision/recall/junk case.

        Segments (all ON-SCREEN, all duration 1.0s < 1.5s except the caption
        which spans 10.0s):
          0. "SEASON FINALE LIVE NOW" [0.0, 10.0] -- matches the one GT text,
             long duration -> matched, not junk.
          1. "Lorem ipsum background one" [1.0, 2.0] -- no GT match, short
             -> junk.
          2. "Lorem ipsum background two" [2.0, 3.0] -- no GT match, short
             -> junk.
          3. "Lorem ipsum background three" [3.0, 4.0] -- no GT match, short
             -> junk.

        Ground truth: one required text, "SEASON FINALE LIVE NOW".

        By hand:
          total_segments = 4
          junk_count = 3 (segments 1, 2, 3)
          junk_rate = 3 / 4 = 0.75
          retained_overlay_recall = 1 / 1 = 1.0 (the one required GT text
            has a matching segment: segment 0)
        """
        segments = [
            _seg("SEASON FINALE LIVE NOW", start=0.0, end=10.0),
            _seg("Lorem ipsum background one", start=1.0, end=2.0),
            _seg("Lorem ipsum background two", start=2.0, end=3.0),
            _seg("Lorem ipsum background three", start=3.0, end=4.0),
        ]
        gt = _gt([("SEASON FINALE LIVE NOW", True)])

        metrics = compute_junk_metrics(segments, gt, fuzzy_threshold=0.85)

        assert metrics.total_segments == 4
        assert metrics.junk_count == 3
        assert metrics.junk_rate == 0.75
        assert metrics.retained_overlay_recall == 1.0

    def test_empty_segments_returns_zero_rate_and_full_recall_when_no_required(self) -> None:
        gt = GroundTruth(language="en", expected_texts=[])
        metrics = compute_junk_metrics([], gt, fuzzy_threshold=0.85)
        assert metrics.total_segments == 0
        assert metrics.junk_count == 0
        assert metrics.junk_rate == 0.0
        assert metrics.retained_overlay_recall == 1.0

    def test_dropped_required_overlay_lowers_retained_recall(self) -> None:
        """Dropping the matching segment shows up in retained_overlay_recall."""
        segments = [_seg("Lorem ipsum background one", start=1.0, end=2.0)]
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        metrics = compute_junk_metrics(segments, gt, fuzzy_threshold=0.85)
        assert metrics.retained_overlay_recall == 0.0

    def test_speech_segments_excluded_from_total(self) -> None:
        segments = [
            _seg("Some speech", start=0.0, end=1.0, source="SPEECH"),
            _seg("SEASON FINALE LIVE NOW", start=0.0, end=10.0),
        ]
        gt = _gt([("SEASON FINALE LIVE NOW", True)])
        metrics = compute_junk_metrics(segments, gt, fuzzy_threshold=0.85)
        assert metrics.total_segments == 1
        assert metrics.junk_count == 0
