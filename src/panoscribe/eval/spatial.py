"""Cross-frame position-stability diagnostic for the OCR eval harness (phase 4).

See ``docs/plans/2026-08-28-ocr-phase4-crossmodal-spatial.md`` for the full
argument. Summary: every non-background fixture element used to sit at a
hardcoded, unjittered position, making "is this segment's position stable
across frames?" a degenerate signal -- everything non-background was
equally "stable". This module measures the statistic properly (now that the
fixture has a genuinely position-unstable required overlay) so the
combination of size and position-stability can be evaluated honestly,
including against the pre-existing small-and-stable junk counterexample
(``STUDIO NINE FEED``).

Cross-frame identity reuses
:func:`panoscribe.ocr._text_match.cluster_canonical_keys` -- the same
greedy fuzzy clustering :func:`panoscribe.ocr.ui_filter.filter_by_frequency`
uses to decide "is this the same overlay across frames?" -- rather than
inventing a second notion of "same text" for spatial purposes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from panoscribe.ocr._text_match import _canonical_key, cluster_canonical_keys

if TYPE_CHECKING:
    from panoscribe.ocr.rapid_ocr import SegmentGeometry

#: Default fuzzy-match threshold for cross-frame identity clustering, in
#: ``[0.0, 1.0]``. Matches ``filter_by_frequency``'s default (``90.0`` on
#: its 0-100 scale) -- the same identity notion, same threshold.
DEFAULT_FUZZY_THRESHOLD: float = 0.90


@dataclass(frozen=True)
class ClusterSpatialStats:
    """Per-identity-cluster spatial-stability + typography summary.

    ``position_stability`` is ``None`` when the cluster has exactly one
    occurrence -- dispersion is undefined for a single point. Treating a
    single occurrence as "perfectly stable" (0.0) would make it
    indistinguishable from a genuinely repeated, genuinely static overlay,
    contaminating any aggregate statistic over the matched/unmatched
    groups. Callers must report single-occurrence clusters separately, not
    average them in as zeros.
    """

    canonical_text: str
    occurrence_count: int
    mean_normalized_height: float
    position_stability: float | None
    matched: bool


def compute_cluster_spatial_stats(
    geometry: list[SegmentGeometry],
    matched_flags: list[bool],
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> list[ClusterSpatialStats]:
    """Cluster ``geometry`` by cross-frame text identity; compute per-cluster stats.

    ``matched_flags[i]`` must correspond to ``geometry[i]`` (same order,
    same source list the caller scored against ground truth) -- typically
    :func:`panoscribe.eval.junk.is_matched_to_ground_truth` evaluated
    per-segment at the raw stage, mirroring ``scripts/eval_ocr.py``'s
    ``--typography`` diagnostic. A cluster's ``matched`` flag is ``True`` if
    ANY of its occurrences matched -- clusters are per-canonical-text, not
    per-occurrence, so one OCR misread within an otherwise-matching cluster
    should not flip the whole cluster to "junk".

    ``position_stability`` is the population-RMS dispersion of
    ``(x_center_norm, y_center_norm)`` around the cluster's centroid --
    ``sqrt(var(x) + var(y))`` -- expressed in the same frame-relative units
    as ``normalized_height`` (both are ratios of pixel measurements to
    frame dimensions). ``0.0`` means every occurrence rendered at the exact
    same relative position; larger values mean more cross-frame movement.

    Raises ``ValueError`` if ``geometry`` and ``matched_flags`` differ in
    length -- they must be index-aligned.
    """
    if len(geometry) != len(matched_flags):
        raise ValueError(
            f"geometry ({len(geometry)}) and matched_flags ({len(matched_flags)}) "
            "must be the same length and index-aligned"
        )

    # Build unique non-empty canonical keys in first-seen order, then
    # cluster with the SAME identity notion filter_by_frequency uses -- not
    # a second one (see module docstring).
    seen_keys: dict[str, None] = {}
    for geo in geometry:
        key = _canonical_key(geo.text)
        if key:
            seen_keys.setdefault(key, None)
    clusters = cluster_canonical_keys(seen_keys.keys(), fuzzy_threshold)

    key_to_cluster_id: dict[str, int] = {}
    for cluster_id, cluster in enumerate(clusters):
        for key in cluster:
            key_to_cluster_id[key] = cluster_id

    members_by_cluster: dict[int, list[int]] = defaultdict(list)
    for idx, geo in enumerate(geometry):
        key = _canonical_key(geo.text)
        if not key:
            continue
        members_by_cluster[key_to_cluster_id[key]].append(idx)

    stats: list[ClusterSpatialStats] = []
    for indices in members_by_cluster.values():
        n = len(indices)
        heights = [geometry[i].normalized_height for i in indices]
        mean_height = sum(heights) / n
        matched = any(matched_flags[i] for i in indices)
        position_stability: float | None
        if n > 1:
            xs = [geometry[i].x_center_norm for i in indices]
            ys = [geometry[i].y_center_norm for i in indices]
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            var_x = sum((x - mean_x) ** 2 for x in xs) / n
            var_y = sum((y - mean_y) ** 2 for y in ys) / n
            position_stability = math.sqrt(var_x + var_y)
        else:
            position_stability = None
        stats.append(
            ClusterSpatialStats(
                canonical_text=geometry[indices[0]].text,
                occurrence_count=n,
                mean_normalized_height=mean_height,
                position_stability=position_stability,
                matched=matched,
            )
        )

    stats.sort(key=lambda s: (-s.occurrence_count, s.canonical_text))
    return stats


def format_joint_distribution_table(stats: list[ClusterSpatialStats]) -> str:
    """Render ``stats`` as a plain-text table: text, matched, n, height, stability.

    Single-occurrence clusters (``position_stability is None``) print
    ``"n/a (n=1)"`` rather than a numeric value -- see
    :class:`ClusterSpatialStats`'s docstring for why they must not be
    conflated with a measured ``0.0``.
    """
    header = f"{'text':<40} {'matched':>7} {'n':>3} {'height':>8} {'stability':>10}"
    sep = "-" * len(header)
    lines = [header, sep]
    for s in stats:
        stability_str = (
            f"{s.position_stability:.4f}" if s.position_stability is not None else "n/a (n=1)"
        )
        text_display = (
            s.canonical_text if len(s.canonical_text) <= 40 else s.canonical_text[:37] + "..."
        )
        lines.append(
            f"{text_display:<40} {s.matched!s:>7} {s.occurrence_count:>3} "
            f"{s.mean_normalized_height:>8.4f} {stability_str:>10}"
        )
    return chr(10).join(lines)
