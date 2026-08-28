"""Unit tests for panoscribe.eval.spatial (phase-4 position-stability diagnostic)."""

from __future__ import annotations

import pytest

from panoscribe.eval.spatial import (
    ClusterSpatialStats,
    compute_cluster_spatial_stats,
    format_joint_distribution_table,
)
from panoscribe.ocr.rapid_ocr import SegmentGeometry


def _geo(
    text: str,
    *,
    height: float = 0.05,
    x: float = 0.5,
    y: float = 0.5,
) -> SegmentGeometry:
    return SegmentGeometry(
        text=text,
        start=0.0,
        end=0.0,
        normalized_height=height,
        y_center=y * 480,
        x_center=x * 640,
        y_center_norm=y,
        x_center_norm=x,
    )


class TestComputeClusterSpatialStats:
    def test_raises_on_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            compute_cluster_spatial_stats([_geo("a")], [])

    def test_single_occurrence_cluster_has_no_stability(self) -> None:
        stats = compute_cluster_spatial_stats([_geo("TRAFFIC ALERT NOW")], [True])
        assert len(stats) == 1
        assert stats[0].occurrence_count == 1
        assert stats[0].position_stability is None
        assert stats[0].matched is True

    def test_perfectly_stable_cluster_has_zero_stability(self) -> None:
        geometry = [_geo("STUDIO NINE FEED", x=0.6, y=0.5) for _ in range(5)]
        stats = compute_cluster_spatial_stats(geometry, [False] * 5)
        assert len(stats) == 1
        assert stats[0].occurrence_count == 5
        assert stats[0].position_stability == pytest.approx(0.0)
        assert stats[0].matched is False

    def test_moving_cluster_has_positive_stability(self) -> None:
        geometry = [_geo("SPORTS SCORE UPDATE LIVE", x=x) for x in (0.1, 0.3, 0.5, 0.7)]
        stats = compute_cluster_spatial_stats(geometry, [True] * 4)
        assert len(stats) == 1
        assert stats[0].position_stability > 0.0

    def test_fuzzy_near_duplicates_join_one_cluster(self) -> None:
        geometry = [_geo("Subscribe"), _geo("SUBSCRIBE!"), _geo("subscribe ")]
        stats = compute_cluster_spatial_stats(geometry, [False, False, False])
        assert len(stats) == 1
        assert stats[0].occurrence_count == 3

    def test_distinct_texts_form_separate_clusters(self) -> None:
        geometry = [_geo("SEASON FINALE LIVE NOW"), _geo("lorem ipsum dolor sit amet")]
        stats = compute_cluster_spatial_stats(geometry, [True, False])
        assert len(stats) == 2

    def test_cluster_matched_if_any_occurrence_matched(self) -> None:
        geometry = [_geo("BREAKING NEWS UPDATE"), _geo("BREAKING NEWS UPDATE")]
        stats = compute_cluster_spatial_stats(geometry, [False, True])
        assert len(stats) == 1
        assert stats[0].matched is True

    def test_empty_canonical_text_excluded_from_clusters(self) -> None:
        geometry = [_geo("   "), _geo("real text")]
        stats = compute_cluster_spatial_stats(geometry, [False, True])
        assert len(stats) == 1
        assert stats[0].canonical_text == "real text"

    def test_empty_geometry_returns_no_clusters(self) -> None:
        assert compute_cluster_spatial_stats([], []) == []

    def test_mean_normalized_height_is_the_cluster_average(self) -> None:
        geometry = [_geo("x", height=0.02), _geo("x", height=0.04)]
        stats = compute_cluster_spatial_stats(geometry, [True, True])
        assert stats[0].mean_normalized_height == pytest.approx(0.03)


class TestFormatJointDistributionTable:
    def test_reports_na_for_single_occurrence_clusters(self) -> None:
        stats = [
            ClusterSpatialStats(
                canonical_text="TRAFFIC ALERT NOW",
                occurrence_count=1,
                mean_normalized_height=0.05,
                position_stability=None,
                matched=True,
            )
        ]
        table = format_joint_distribution_table(stats)
        assert "n/a (n=1)" in table

    def test_reports_numeric_stability_when_measurable(self) -> None:
        stats = [
            ClusterSpatialStats(
                canonical_text="SPORTS SCORE UPDATE LIVE",
                occurrence_count=4,
                mean_normalized_height=0.03,
                position_stability=0.1234,
                matched=True,
            )
        ]
        table = format_joint_distribution_table(stats)
        assert "0.1234" in table

    def test_empty_stats_still_prints_header(self) -> None:
        table = format_joint_distribution_table([])
        assert "text" in table
        assert "stability" in table


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
