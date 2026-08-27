#!/usr/bin/env python3
"""Deterministic synthetic-fixture generator for OCR junk-segment measurement.

Synthesizes a short "slide sequence" with:

* A text-heavy paragraph rendered in the background of every frame, jittered
  by a few pixels per frame via a seeded RNG. Real per-frame OCR instability
  (subpixel antialiasing shifts, partial character clipping at the jittered
  position) is reproduced by the OCR engine itself running against these
  frames -- this script does not fake OCR output.
* A main deliberate overlay caption rendered at a fixed position, shown in
  most (not all) frames so its frequency ratio stays below the default
  ``frequency_threshold`` (0.95) while still being "stable" (never jittered,
  identical text every time it appears).
* Two SHORT-LIVED deliberate overlays (1-2 sampled frames each) that MUST be
  retained -- these are what a naive low-recurrence-count filter would
  destroy invisibly, and what phase 1's ">= 1 match anywhere" recall
  predicate could not detect the loss of (see
  ``docs/plans/2026-08-27-ocr-phase2-stability.md``, step 1).
* STABLE JUNK -- a static "channel bug" watermark that persists across most
  (not all) frames, below the frequency-filter drop threshold. This is junk
  the recurrence signal structurally cannot catch (it never crosses the
  ratio bound), and its absence from the phase-1 fixture flattered any
  recurrence-based filter.
* UI CHROME (a SUBSCRIBE button + an @handle) matching the YouTube platform
  profile's ``ui_text_patterns``, rendered OUTSIDE that profile's
  ``ui_exclusion_zones`` so OCR actually reads it before the pattern filter
  runs -- unlike the phase-1 fixture, which only ever resolved to
  ``GENERIC_PROFILE`` (empty patterns), making the pattern filter untestable
  by construction.

Two output modes:

* ``write_fixture`` (default) -- a directory of PNG frames for
  ``scripts/eval_ocr.py --images``. Kept for continuity with the phase-1
  measurement.
* ``write_video_fixture`` (``--video``) -- a single lossless (FFV1-in-AVI)
  video file for ``scripts/eval_ocr.py VIDEO``, so scene-change gating and
  zone masking (both ``--images``-mode no-ops) actually participate. This is
  the mode phase 2's baseline is measured against -- the phase-1 baseline
  only ever exercised ``--images``, but the README's reported failure is
  about video.

Usage
-----
    python scripts/generate_ocr_noise_fixture.py OUTPUT_DIR
        [--seed SEED] [--num-frames N] [--video] [--fps FPS]

Images mode writes ``OUTPUT_DIR/frame-00.png`` .. ``frame-NN.png`` and
``OUTPUT_DIR/ground_truth.json``. Video mode writes ``OUTPUT_DIR/fixture.avi``
and ``OUTPUT_DIR/ground_truth.json`` (conforming to
``panoscribe.eval.models.GroundTruth``, including the optional
``appearances`` field for per-appearance recall scoring).

Determinism
-----------
All randomness is drawn from ``numpy.random.default_rng(seed)`` -- no global
RNG state is touched. Two runs with the same ``seed``/``num_frames`` produce
byte-identical *decoded* frame arrays (see ``generate_frames``). PNG-encoded
bytes are not asserted byte-identical across zlib versions; the fixture's
reproducibility claim is about the decoded pixel data, which is what OCR
actually consumes. The video path uses the lossless FFV1 codec specifically
so the same claim holds for the video container -- a lossy codec (e.g.
mp4v) would make decoded-from-file frames diverge from the in-memory arrays,
which would silently weaken this exact guarantee.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

_FRAME_W = 640
_FRAME_H = 480
_DEFAULT_NUM_FRAMES = 12
_DEFAULT_SEED = 42
_JITTER_PX = 3

# Background paragraph text (deliberately not listed in ground truth -- it
# must never be recognized as a deliberate caption). Chosen to be lexically
# far from the overlay caption below so no fuzzy match at >= 0.85 is
# possible even under OCR noise.
#
# A pool larger than the per-frame window (4 lines): each frame renders a
# 4-line *window* starting at a random offset into this pool, so
# consecutive frames show genuinely different text -- not the same text
# re-detected with pixel-level noise. A pure position-jitter design was
# tried first and failed to reproduce the junk problem at all: RapidOCR
# recognized the same 4 static lines identically across every jittered
# frame, so ``filter_by_frequency`` caught 100% of it (see the plan doc's
# "Findings" section for the measured funnel). Sliding the window is closer
# to the real-world cause of instability -- scrolling/changing background
# text, not merely noisy detection of static text -- and is what the
# baseline below is measured against.
_BACKGROUND_LINE_POOL = [
    "Lorem ipsum dolor sit amet consectetur",
    "adipiscing elit sed do eiusmod tempor",
    "incididunt ut labore et dolore magna",
    "aliqua ut enim ad minim veniam quis",
    "nostrud exercitation ullamco laboris",
    "nisi ut aliquip ex ea commodo consequat",
    "duis aute irure dolor in reprehenderit",
    "voluptate velit esse cillum dolore eu",
    "fugiat nulla pariatur excepteur sint",
    "occaecat cupidatat non proident sunt",
    "culpa qui officia deserunt mollit anim",
    "id est laborum sed ut perspiciatis unde",
]
_WINDOW_LINES = 4

# Deliberate overlay caption -- must be retained by the pipeline. Shown at a
# fixed position, never jittered, and skipped in a minority of frames so the
# frequency ratio stays under the default 0.95 drop threshold while the
# caption is still overwhelmingly the majority signal (a real "stable
# caption" pattern).
_OVERLAY_TEXT = "SEASON FINALE LIVE NOW"
_OVERLAY_Y = 380
_OVERLAY_SKIP_FRAME_INDICES = frozenset({2, 7})

# Short-lived REAL overlays -- 1-2 sampled frames each, required=True. A
# naive "appeared in < N frames -> drop" filter would destroy these
# invisibly; phase 1's fixture had no such case, so it could not fail a
# filter that would break real short-lived captions (burned-in subtitles,
# fast lower-thirds).
_SHORT_LIVED_A_TEXT = "BREAKING NEWS UPDATE"
_SHORT_LIVED_A_Y = 300
_SHORT_LIVED_A_FRAME_INDICES = frozenset({4})

_SHORT_LIVED_B_TEXT = "FLASH SALE ENDS SOON"
_SHORT_LIVED_B_Y = 335
_SHORT_LIVED_B_FRAME_INDICES = frozenset({9, 10})

# Stable junk -- a static "channel bug" watermark. Persists across most (not
# all) frames but stays below the default frequency-filter drop threshold
# (0.95), so recurrence-based filtering structurally cannot remove it. Not
# listed in ground truth -- it must never fuzzy-match a required text.
_STABLE_JUNK_TEXT = "STUDIO NINE FEED"
_STABLE_JUNK_Y = 265
_STABLE_JUNK_X = 380
_STABLE_JUNK_SKIP_FRAME_INDICES = frozenset({1, 5, 9})

# UI chrome matching the YouTube platform profile's ``ui_text_patterns``
# (see ``panoscribe.platforms.youtube``), rendered OUTSIDE that profile's
# ``ui_exclusion_zones`` (right edge x>=0.88, bottom band y>=0.88, top band
# y<=0.05 of a 640x480 frame) so OCR reads it before the pattern filter
# runs -- unlike phase 1, where the fixture only ever resolved to
# GENERIC_PROFILE (empty patterns) and the pattern filter was untestable.
_CHROME_SUBSCRIBE_TEXT = "SUBSCRIBE"
_CHROME_SUBSCRIBE_Y = 195
_CHROME_HANDLE_TEXT = "@creator_handle"
_CHROME_HANDLE_Y = 230
_CHROME_X = 40


class Fixture(NamedTuple):
    """In-memory generator output: decoded frames + ground-truth dict."""

    frames: list[np.ndarray]
    ground_truth: dict[str, object]


def generate_frames(
    num_frames: int = _DEFAULT_NUM_FRAMES,
    seed: int = _DEFAULT_SEED,
) -> Fixture:
    """Build ``num_frames`` deterministic BGR frames plus matching ground truth.

    Same ``(num_frames, seed)`` always produces identical pixel arrays --
    all jitter is drawn from a seeded ``numpy.random.default_rng``, not
    global RNG state.
    """
    rng = np.random.default_rng(seed)
    frames: list[np.ndarray] = []

    max_start = len(_BACKGROUND_LINE_POOL) - _WINDOW_LINES

    for i in range(num_frames):
        frame = np.full((_FRAME_H, _FRAME_W, 3), 235, dtype=np.uint8)

        # Sliding-window background paragraph -- each frame shows a
        # different 4-line window into the pool (plus a few pixels of
        # jitter), reproducing real per-frame detection instability instead
        # of static text with cosmetic noise.
        window_start = int(rng.integers(0, max_start + 1))
        window = _BACKGROUND_LINE_POOL[window_start : window_start + _WINDOW_LINES]
        dx = int(rng.integers(-_JITTER_PX, _JITTER_PX + 1))
        dy = int(rng.integers(-_JITTER_PX, _JITTER_PX + 1))
        y0 = 60 + dy
        for line_idx, line in enumerate(window):
            y = y0 + line_idx * 32
            cv2.putText(
                frame,
                line,
                (30 + dx, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (40, 40, 40),
                1,
                cv2.LINE_AA,
            )

        # Stable deliberate overlay caption -- fixed position, no jitter,
        # skipped in a minority of frames.
        if i not in _OVERLAY_SKIP_FRAME_INDICES:
            cv2.putText(
                frame,
                _OVERLAY_TEXT,
                (40, _OVERLAY_Y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 0),
                2,
                cv2.LINE_AA,
            )

        # Short-lived REAL overlays -- must be retained despite appearing in
        # only 1-2 frames.
        if i in _SHORT_LIVED_A_FRAME_INDICES:
            cv2.putText(
                frame,
                _SHORT_LIVED_A_TEXT,
                (40, _SHORT_LIVED_A_Y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
        if i in _SHORT_LIVED_B_FRAME_INDICES:
            cv2.putText(
                frame,
                _SHORT_LIVED_B_TEXT,
                (40, _SHORT_LIVED_B_Y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # Stable junk -- static watermark, persists across most frames but
        # never listed in ground truth.
        if i not in _STABLE_JUNK_SKIP_FRAME_INDICES:
            cv2.putText(
                frame,
                _STABLE_JUNK_TEXT,
                (_STABLE_JUNK_X, _STABLE_JUNK_Y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (60, 60, 60),
                1,
                cv2.LINE_AA,
            )

        # UI chrome matching the YouTube profile's patterns -- every frame,
        # positioned outside that profile's exclusion zones.
        cv2.putText(
            frame,
            _CHROME_SUBSCRIBE_TEXT,
            (_CHROME_X, _CHROME_SUBSCRIBE_Y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            _CHROME_HANDLE_TEXT,
            (_CHROME_X, _CHROME_HANDLE_Y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

        frames.append(frame)

    def _appearances(skip_indices: frozenset[int]) -> list[tuple[float, float]]:
        # Point windows -- (timestamp, timestamp) -- deliberately overlap
        # both video-mode segments (start == end == timestamp) and
        # images-mode segments (start=i, end=i+1) under
        # ``panoscribe.eval.junk._within_window``'s boundary-inclusive
        # overlap check, without touching adjacent frames' windows (each
        # window is a single point, not a range).
        return [(float(i), float(i)) for i in range(num_frames) if i not in skip_indices]

    gt_dict: dict[str, object] = {
        "language": "en",
        "expected_texts": [
            {
                "text": _OVERLAY_TEXT,
                "required": True,
                "appearances": _appearances(_OVERLAY_SKIP_FRAME_INDICES),
            },
            {
                "text": _SHORT_LIVED_A_TEXT,
                "required": True,
                "appearances": [(float(i), float(i)) for i in sorted(_SHORT_LIVED_A_FRAME_INDICES)],
            },
            {
                "text": _SHORT_LIVED_B_TEXT,
                "required": True,
                "appearances": [(float(i), float(i)) for i in sorted(_SHORT_LIVED_B_FRAME_INDICES)],
            },
        ],
    }
    return Fixture(frames=frames, ground_truth=gt_dict)


def write_fixture(output_dir: Path, num_frames: int, seed: int) -> None:
    """Generate and write frames + ``ground_truth.json`` to ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = generate_frames(num_frames=num_frames, seed=seed)
    for i, frame in enumerate(fixture.frames):
        out_path = output_dir / f"frame-{i:02d}.png"
        cv2.imwrite(str(out_path), frame)
    gt_path = output_dir / "ground_truth.json"
    gt_path.write_text(json.dumps(fixture.ground_truth, indent=2), encoding="utf-8")


#: Video filename written by :func:`write_video_fixture`.
VIDEO_FILENAME = "fixture.avi"

#: Default video sample rate. Matches
#: ``panoscribe.config.PanoScribeConfig.ocr_sample_fps``'s default so that,
#: with ``stride == 1``, sampled-frame timestamp ``i`` lines up exactly with
#: generator frame index ``i`` and the ``appearances`` point-windows in
#: ``generate_frames`` need no unit conversion.
_DEFAULT_VIDEO_FPS = 1.0


def write_video_fixture(
    output_dir: Path,
    num_frames: int,
    seed: int,
    fps: float = _DEFAULT_VIDEO_FPS,
) -> Path:
    """Generate and write a single lossless video + ``ground_truth.json``.

    Uses the FFV1 codec in an AVI container -- lossless, so decoded frames
    read back from the file are ``numpy.array_equal`` to the in-memory
    arrays :func:`generate_frames` produced (verified in
    ``tests/test_generate_ocr_noise_fixture.py``). A lossy codec (e.g.
    mp4v) would not support that claim and would silently change what the
    OCR engine sees between runs/platforms.

    Returns the path to the written video file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = generate_frames(num_frames=num_frames, seed=seed)
    video_path = output_dir / VIDEO_FILENAME
    height, width = fixture.frames[0].shape[:2]
    fourcc = cv2.VideoWriter.fourcc(*"FFV1")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))
    try:
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open VideoWriter for {video_path}")
        for frame in fixture.frames:
            writer.write(frame)
    finally:
        writer.release()
    gt_path = output_dir / "ground_truth.json"
    gt_path.write_text(json.dumps(fixture.ground_truth, indent=2), encoding="utf-8")
    return video_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=str, help="Directory to write frames + GT into.")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--num-frames", type=int, default=_DEFAULT_NUM_FRAMES)
    parser.add_argument(
        "--video",
        action="store_true",
        help=(
            "Write a single lossless (FFV1/AVI) video file instead of a "
            "directory of PNGs -- exercises scene-change gating and zone "
            "masking, which --images mode always no-ops."
        ),
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=_DEFAULT_VIDEO_FPS,
        help="Video sample rate (--video mode only). Default matches ocr_sample_fps.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    output_dir = Path(args.output_dir)
    if args.video:
        video_path = write_video_fixture(
            output_dir, num_frames=args.num_frames, seed=args.seed, fps=args.fps
        )
        print(f"Wrote {args.num_frames}-frame video ({video_path}) + ground_truth.json")
    else:
        write_fixture(output_dir, num_frames=args.num_frames, seed=args.seed)
        print(f"Wrote {args.num_frames} frames + ground_truth.json to {args.output_dir}")


if __name__ == "__main__":
    main()
