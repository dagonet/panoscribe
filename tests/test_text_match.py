"""Unit tests for panoscribe.ocr._text_match.

Covers the two private helpers shared by the deduplicator and the
frequency filter:

* ``_canonical_key`` — case-folded, edge-stripped bucket key.
* ``_fuzzy_match`` — boolean similarity gate based on
  ``rapidfuzz.fuzz.ratio`` against a ``[0.0, 1.0]`` threshold.

These tests pin the boundary semantics (identical strings, empty
strings, near-duplicates above threshold, distinct strings below
threshold) so the deduplicator refactor is provably behavior-
preserving and the new ``filter_by_frequency`` clustering step
inherits the same gate.
"""

from __future__ import annotations

import pytest

from panoscribe.ocr._text_match import _canonical_key, _fuzzy_match, cluster_canonical_keys


class TestCanonicalKey:
    """Bucket-key normalization: case-fold + strip whitespace edges."""

    def test_casefolds_uppercase(self) -> None:
        assert _canonical_key("SUBSCRIBE") == "subscribe"

    def test_strips_leading_and_trailing_whitespace(self) -> None:
        assert _canonical_key("   hello   ") == "hello"

    def test_strips_tabs_and_newlines(self) -> None:
        assert _canonical_key("\t\nSubscribe\n\t") == "subscribe"

    def test_preserves_inner_whitespace(self) -> None:
        assert _canonical_key("  hello  world  ") == "hello  world"

    def test_empty_string_returns_empty(self) -> None:
        assert _canonical_key("") == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert _canonical_key("   \n\t  ") == ""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Subscribe", "subscribe"),
            ("SUBSCRIBE!", "subscribe!"),
            ("Subscribe →", "subscribe →"),
        ],
    )
    def test_parametrized(self, raw: str, expected: str) -> None:
        assert _canonical_key(raw) == expected


class TestFuzzyMatch:
    """Boolean similarity gate: ``fuzz.ratio(a, b) / 100 >= threshold``."""

    def test_identical_strings_match(self) -> None:
        assert _fuzzy_match("hello", "hello", threshold=1.0) is True

    def test_empty_strings_match(self) -> None:
        # rapidfuzz returns 100.0 for two empty strings; treat as a match.
        assert _fuzzy_match("", "", threshold=0.9) is True

    def test_near_duplicate_above_threshold(self) -> None:
        # "SUBSCRIBE!" vs "SUBSCRIBE" — single trailing punctuation
        # difference clears a 0.90 threshold easily.
        assert _fuzzy_match("SUBSCRIBE!", "SUBSCRIBE", threshold=0.90) is True

    def test_distinct_strings_below_threshold(self) -> None:
        assert _fuzzy_match("Hello world", "Random text", threshold=0.90) is False

    def test_threshold_one_rejects_near_duplicate(self) -> None:
        # 1.0 demands an exact-ratio match; a single-char difference fails.
        assert _fuzzy_match("Subscribe", "Subscribe!", threshold=1.0) is False

    def test_threshold_zero_accepts_anything(self) -> None:
        assert _fuzzy_match("alpha", "omega", threshold=0.0) is True

    def test_case_insensitive_via_processor(self) -> None:
        # Helper applies str.lower so case variation does not depress the
        # ratio — matches the deduplicator's pre-existing behavior.
        assert _fuzzy_match("SUBSCRIBE", "subscribe", threshold=0.99) is True


class TestClusterCanonicalKeys:
    """Greedy single-link clustering shared by ``filter_by_frequency`` and
    the phase-4 spatial-stability measurement."""

    def test_identical_keys_join_one_cluster(self) -> None:
        clusters = cluster_canonical_keys(["subscribe", "subscribe"], 0.9)
        assert clusters == [["subscribe", "subscribe"]]

    def test_distinct_keys_form_separate_clusters(self) -> None:
        clusters = cluster_canonical_keys(["hello world", "random text"], 0.9)
        assert clusters == [["hello world"], ["random text"]]

    def test_near_duplicates_join_the_same_cluster(self) -> None:
        clusters = cluster_canonical_keys(["subscribe!", "subscribe", "subscribe "], 0.9)
        assert len(clusters) == 1
        assert set(clusters[0]) == {"subscribe!", "subscribe", "subscribe "}

    def test_third_key_joins_via_any_existing_member_not_just_the_first(self) -> None:
        # "b" only clears threshold against "a2", not the cluster's first
        # member "a1" -- single-link means matching ANY member suffices.
        clusters = cluster_canonical_keys(["hello world", "hemlo world", "hell world"], 0.7)
        assert len(clusters) == 1

    def test_empty_input_returns_no_clusters(self) -> None:
        assert cluster_canonical_keys([], 0.9) == []

    def test_iteration_order_is_deterministic_and_preserved(self) -> None:
        clusters = cluster_canonical_keys(["zeta", "alpha", "mid"], 0.99)
        assert clusters == [["zeta"], ["alpha"], ["mid"]]

    def test_threshold_zero_collapses_everything_into_one_cluster(self) -> None:
        clusters = cluster_canonical_keys(["alpha", "omega", "gamma"], 0.0)
        assert len(clusters) == 1


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
