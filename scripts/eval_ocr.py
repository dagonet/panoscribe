#!/usr/bin/env python3
"""OCR-only evaluation harness for panoscribe.

Usage
-----
    python scripts/eval_ocr.py VIDEO GROUND_TRUTH [--ocr-language LANG]
        [--funnel] [--junk] [--output OUTPUT]

Runs the OCR pipeline (frame sampling -> preprocessing -> UI masking ->
RapidOCR -> aggregation -> pattern filter -> frequency filter -> dedup)
against a video file and scores the result against a ground-truth JSON file.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from panoscribe.config import PanoScribeConfig
from panoscribe.eval.funnel import FunnelCounts
from panoscribe.eval.junk import compute_junk_metrics, is_matched_to_ground_truth
from panoscribe.eval.models import GroundTruth
from panoscribe.eval.scoring import score_video
from panoscribe.eval.spatial import compute_cluster_spatial_stats, format_joint_distribution_table
from panoscribe.ocr.deduplicator import dedup_segments
from panoscribe.ocr.rapid_ocr import RapidOCREngine
from panoscribe.ocr.ui_filter import filter_by_frequency, filter_by_patterns
from panoscribe.platforms.registry import resolve_profile

_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate OCR output against ground truth.",
    )
    parser.add_argument(
        "video",
        type=str,
        nargs="?",
        default=None,
        help="Path to the video file (omit when using --images).",
    )
    parser.add_argument(
        "ground_truth",
        type=str,
        help="Path to the ground-truth JSON file.",
    )
    parser.add_argument(
        "--images",
        type=str,
        default=None,
        help="Directory of slide image files (use instead of video positional).",
    )
    parser.add_argument(
        "--ocr-language",
        default=None,
        help=(
            "RapidOCR LangRec value (e.g. 'en', 'latin'). "
            "Default: from ground-truth JSON 'language' field."
        ),
    )
    parser.add_argument(
        "--funnel",
        action="store_true",
        help="Collect and print funnel diagnostics.",
    )
    parser.add_argument(
        "--junk",
        action="store_true",
        help=(
            "Collect and print junk-segment metrics (count/rate, retained-overlay "
            "recall) at each filtering stage. See panoscribe.eval.junk."
        ),
    )
    parser.add_argument(
        "--no-scene-change",
        action="store_true",
        help="Disable scene-change detection (sample every frame at fps rate).",
    )
    parser.add_argument(
        "--no-ui-filter",
        action="store_true",
        help="Disable pattern and frequency UI filters.",
    )
    parser.add_argument(
        "--platform-profile",
        type=str,
        default=None,
        help=(
            "Explicit platform profile override (e.g. 'youtube', 'tiktok', "
            "'instagram', 'generic'). Default: config's 'auto' URL-based "
            "detection, which resolves to GENERIC_PROFILE (empty patterns) "
            "for local file/directory paths -- pass this to actually "
            "exercise a profile's ui_text_patterns / ui_exclusion_zones "
            "against a synthetic fixture."
        ),
    )
    parser.add_argument(
        "--typography",
        action="store_true",
        help=(
            "Collect per-segment normalized bbox height (raw stage, before "
            "any filter) and print a matched-vs-unmatched separation table. "
            "Diagnostic only -- see panoscribe.ocr.rapid_ocr.SegmentGeometry "
            "and docs/plans/2026-08-28-ocr-phase3-typography.md. Height is "
            "``mean_box_height / frame_height`` (scale-invariant, no resize "
            "in panoscribe.ocr.preprocessor.preprocess)."
        ),
    )
    parser.add_argument(
        "--spatial",
        action="store_true",
        help=(
            "Collect per-cluster position-stability (in addition to "
            "typography) and print the joint height x stability "
            "distribution table for matched vs unmatched clusters. "
            "Diagnostic only -- see panoscribe.eval.spatial and "
            "docs/plans/2026-08-28-ocr-phase4-crossmodal-spatial.md. "
            "Implies the same raw-stage geometry collection as --typography."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Write EvalResult JSON to this path.",
    )
    return parser


def _load_ground_truth(path: str) -> GroundTruth:
    raw = Path(path).read_text(encoding="utf-8")
    return GroundTruth.model_validate_json(raw)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Validate: exactly one of (video, --images).
    if (args.video is None) == (args.images is None):
        parser.error("Exactly one of video (positional) or --images must be provided.")

    # Load ground truth.
    gt = _load_ground_truth(args.ground_truth)
    ocr_language = args.ocr_language or gt.language

    # Build config overridden for evaluation.
    config = PanoScribeConfig()
    config_updates: dict[str, object] = {"ocr_language": ocr_language}
    if args.no_scene_change:
        config_updates["scene_change_enabled"] = False
    if args.platform_profile is not None:
        config_updates["platform_profile"] = args.platform_profile
    config = config.model_copy(update=config_updates)

    # Resolve platform profile (images mode uses the dir path as source).
    source = args.images if args.images is not None else args.video
    profile = resolve_profile(config, source)

    # OCR pipeline (no ASR, no merge).
    ocr_engine = RapidOCREngine(config, profile=profile)
    funnel = FunnelCounts() if args.funnel else None
    geometry: list = [] if (args.typography or args.spatial) else None

    if args.images is not None:
        # Images mode: scan directory for slides.
        image_dir = Path(args.images)
        image_paths = sorted(
            p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
        )
        if not image_paths:
            parser.error(f"No image files found in {args.images}")
        ocr_segments = ocr_engine.extract_images(
            image_paths, timestamps=None, funnel=funnel, geometry=geometry
        )
    else:
        ocr_segments = ocr_engine.extract(Path(args.video), funnel=funnel, geometry=geometry)

    # Snapshot the raw-stage segments now, before the UI-filter block below
    # reassigns ``ocr_segments`` in place. ``geometry`` is index-aligned
    # with THIS list (both are populated together by ``extract``/
    # ``extract_images``); zipping it against the post-filter
    # ``ocr_segments`` instead (as this used to do) silently mispairs
    # segments with the wrong geometry once filtering drops entries from
    # the middle of the list -- see
    # docs/plans/2026-08-28-ocr-phase4-crossmodal-spatial.md.
    raw_segments = list(ocr_segments)

    fuzzy_threshold = config.dedup_similarity_threshold
    junk_stages: dict[str, dict[str, object]] | None = {} if args.junk else None
    if junk_stages is not None:
        junk_stages["raw"] = asdict(
            compute_junk_metrics(ocr_segments, gt, fuzzy_threshold=fuzzy_threshold)
        )

    # UI filters -- same order as cli.py process_single_video.
    if (not args.no_ui_filter) and config.ui_filter_enabled and profile is not None:
        ocr_segments = filter_by_patterns(ocr_segments, profile.ui_text_patterns)
        if funnel is not None:
            funnel.post_pattern_filter = len(ocr_segments)
        if junk_stages is not None:
            junk_stages["post_pattern_filter"] = asdict(
                compute_junk_metrics(ocr_segments, gt, fuzzy_threshold=fuzzy_threshold)
            )

        ocr_segments = filter_by_frequency(
            ocr_segments,
            ocr_engine.last_frame_count,
            profile.frequency_threshold,
            min_frame_count=config.ocr_frequency_min_frame_count,
        )
        if funnel is not None:
            funnel.post_frequency_filter = len(ocr_segments)
        if junk_stages is not None:
            junk_stages["post_frequency_filter"] = asdict(
                compute_junk_metrics(ocr_segments, gt, fuzzy_threshold=fuzzy_threshold)
            )
    elif funnel is not None:
        funnel.post_pattern_filter = len(ocr_segments)
        funnel.post_frequency_filter = len(ocr_segments)

    # Dedup.
    deduped = dedup_segments(
        ocr_segments,
        threshold=config.dedup_similarity_threshold,
        min_duration=config.dedup_min_duration,
        gap_tolerance=2.0 / config.ocr_sample_fps,
    )
    if funnel is not None:
        funnel.post_dedup = len(deduped)
    if junk_stages is not None:
        junk_stages["post_dedup"] = asdict(
            compute_junk_metrics(deduped, gt, fuzzy_threshold=fuzzy_threshold)
        )

    # After merge-like step: final on-screen + both count.
    on_screen = sum(1 for s in deduped if s.source in ("ON-SCREEN", "BOTH"))
    if funnel is not None:
        funnel.final_on_screen_both = on_screen

    # Score.
    result = score_video(deduped, gt, fuzzy_threshold=config.dedup_similarity_threshold)

    # Attach funnel data if collected.
    if funnel is not None:
        result.funnel = asdict(funnel)
    if junk_stages is not None:
        result.junk = junk_stages

    # Typography diagnostic: raw-stage (pre-filter) normalized height,
    # matched vs unmatched. See --typography help and
    # docs/plans/2026-08-28-ocr-phase3-typography.md step 3.
    typography_str = ""
    matched_flags: list[bool] = []
    if geometry:
        fuzzy_threshold_typo = config.dedup_similarity_threshold
        matched_heights = []
        unmatched_heights = []
        for seg, geo in zip(raw_segments, geometry, strict=True):
            is_matched = is_matched_to_ground_truth(seg, gt, fuzzy_threshold_typo)
            matched_flags.append(is_matched)
            bucket = matched_heights if is_matched else unmatched_heights
            bucket.append(geo.normalized_height)

        def _stats(values: list[float]) -> str:
            if not values:
                return "n=0"
            return (
                f"n={len(values)} min={min(values):.4f} "
                f"max={max(values):.4f} mean={sum(values) / len(values):.4f}"
            )

        if args.typography:
            typography_str = (
                chr(10) * 2 + "Typography diagnostic (raw stage, normalized height = "
                "mean_box_height / frame_height; post-CLAHE, no resize):"
                + chr(10)
                + f"  matched (real overlays):   {_stats(matched_heights)}"
                + chr(10)
                + f"  unmatched (junk):          {_stats(unmatched_heights)}"
            )

    # Spatial diagnostic (phase 4): per-cluster position-stability joined
    # with normalized height, matched vs unmatched. See --spatial help and
    # docs/plans/2026-08-28-ocr-phase4-crossmodal-spatial.md.
    spatial_str = ""
    if args.spatial and geometry:
        cluster_stats = compute_cluster_spatial_stats(geometry, matched_flags)
        spatial_str = (
            chr(10) * 2 + "Spatial diagnostic (raw stage, per identity-cluster; "
            "position_stability = sqrt(var(x_center_norm) + var(y_center_norm)), "
            "n/a when a cluster has only 1 occurrence):"
            + chr(10)
            + format_joint_distribution_table(cluster_stats)
        )

    # Console output.
    funnel_str = ""
    if args.funnel and funnel is not None:
        funnel_str = chr(10) * 2 + funnel.report()
    print(
        result.model_dump_json(indent=2) + funnel_str + typography_str + spatial_str,
    )

    # File output.
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(chr(10) + "Wrote evaluation result to " + str(out_path), file=sys.stderr)

    # Exit code: non-zero if recall < 1.0 or precision < 1.0.
    if result.recall < 1.0 or result.precision < 1.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
