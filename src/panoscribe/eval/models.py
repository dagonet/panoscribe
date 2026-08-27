"""Pydantic models for the OCR evaluation harness."""

from __future__ import annotations

from pydantic import BaseModel


class ExpectedText(BaseModel):
    """A single expected text string from the ground truth."""

    text: str
    start: float | None = None
    end: float | None = None
    required: bool = True
    appearances: list[tuple[float, float]] | None = None
    """Optional list of ``(start, end)`` windows this text is expected to
    appear in, e.g. one window per sampled frame it is shown in. When
    present, ``panoscribe.eval.junk.compute_junk_metrics``'s
    ``retained_overlay_recall`` scores each appearance independently
    (partial loss is visible) instead of the coarser ``>= 1 match anywhere
    in [start, end]`` check used when ``appearances`` is absent. Optional
    and additive -- existing ground-truth files without this field keep
    the original coarse behaviour unchanged."""


class GroundTruth(BaseModel):
    """Ground truth data for one video."""

    language: str
    expected_texts: list[ExpectedText]


class EvalResult(BaseModel):
    """Result of scoring OCR output against ground truth."""

    recall: float
    precision: float
    mean_match_similarity: float | None = None
    per_text_results: list[dict] = []
    funnel: dict | None = None
    junk: dict | None = None
    """Junk/noise-segment metrics; see ``panoscribe.eval.junk.JunkMetrics``,
    ``docs/plans/2026-08-27-ocr-noise-measurement.md`` (phase-1 origin) and
    ``docs/plans/2026-08-27-ocr-phase2-stability.md`` (phase-2 metric
    correction -- ``unmatched_rate`` is authoritative, ``junk_rate`` is
    phase-1-only). ``None`` unless the caller opts in
    (``scripts/eval_ocr.py --junk``)."""
