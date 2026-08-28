"""Private text-matching primitives shared across OCR pipeline stages.

Both :mod:`panoscribe.ocr.deduplicator` (cross-frame clustering) and
:mod:`panoscribe.ocr.ui_filter` (frequency-filter clustering) need the
same notion of "are these two OCR strings the same overlay?". A single
shared helper keeps the two stages from drifting on whitespace /
case-folding / similarity-threshold semantics — a kind of subtle
inconsistency that bites users when noise gets through.

The module is private (``_``-prefixed) — these helpers are an
implementation detail of the OCR pipeline, not a public API.

Both helpers are pure functions; no I/O, no logging, no global state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from collections.abc import Iterable


def _canonical_key(text: str) -> str:
    """Bucket key for OCR text grouping: case-folded, edge-stripped.

    Preserves inner whitespace — only leading and trailing whitespace
    (spaces, tabs, newlines) is removed. ``str.casefold`` is preferred
    over ``str.lower`` for full Unicode-aware case folding (matters for
    locales we may yet encounter).
    """
    return text.casefold().strip()


def _fuzzy_match(a: str, b: str, threshold: float) -> bool:
    """Return ``True`` when ``a`` and ``b`` clear a similarity threshold.

    Similarity is ``rapidfuzz.fuzz.ratio(a, b, processor=str.lower) / 100``
    in ``[0.0, 1.0]``. The ``str.lower`` processor keeps case variation
    inside a bucket from depressing the score. ``threshold`` is the
    inclusive lower bound — ``ratio >= threshold`` matches.

    Two empty strings score 100 in rapidfuzz and therefore match at any
    threshold ``<= 1.0``; callers that want to exclude empty strings
    must filter them upstream (the deduplicator does this via
    :func:`_canonical_key` returning ``""``).
    """
    similarity = fuzz.ratio(a, b, processor=str.lower) / 100.0
    return similarity >= threshold


def cluster_canonical_keys(keys: Iterable[str], fuzzy_threshold: float) -> list[list[str]]:
    """Greedy single-link clustering of already-canonical text keys.

    A key joins the first existing cluster where it :func:`_fuzzy_match`\\ es
    *any* member at ``fuzzy_threshold`` (0.0-1.0); otherwise it starts a new
    cluster. Iteration follows ``keys``' own order, so the result is
    deterministic for a deterministic input order (e.g. a ``Counter``'s
    insertion order in CPython 3.7+) and does not re-sort.

    This is the single notion of "are these two OCR strings the same
    overlay across frames?" shared by
    :func:`panoscribe.ocr.ui_filter.filter_by_frequency` (recurrence
    clustering) and the phase-4 spatial-stability measurement
    (``panoscribe.eval.spatial``) -- see
    ``docs/plans/2026-08-28-ocr-phase4-crossmodal-spatial.md``. Callers are
    responsible for excluding empty/meaningless keys before calling this
    (e.g. ``filter_by_frequency`` drops ``""`` upstream); an empty key
    clusters with anything under :func:`_fuzzy_match`'s empty-string rule,
    which is almost never what a caller wants.

    Duplicate keys in ``keys`` are each processed (and each ends up in the
    cluster its first occurrence joined) -- callers that only care about
    *unique* keys should deduplicate before calling.
    """
    clusters: list[list[str]] = []
    for key in keys:
        joined = False
        for cluster in clusters:
            if any(_fuzzy_match(key, member, fuzzy_threshold) for member in cluster):
                cluster.append(key)
                joined = True
                break
        if not joined:
            clusters.append([key])
    return clusters
