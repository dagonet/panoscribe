#!/usr/bin/env python3
"""Deterministic synthetic-fixture generator for OCR junk-segment measurement.

Synthesizes a short "slide sequence" (a directory of PNG frames, treated by
``scripts/eval_ocr.py --images`` as one photo-post frame per file) with:

* A text-heavy paragraph rendered in the background of every frame, jittered
  by a few pixels per frame via a seeded RNG. Real per-frame OCR instability
  (subpixel antialiasing shifts, partial character clipping at the jittered
  position) is reproduced by the OCR engine itself running against these
  frames -- this script does not fake OCR output.
* A small number of deliberate overlay captions rendered at a fixed position,
  shown in most (not all) frames so their frequency ratio stays below the
  default ``frequency_threshold`` (0.95) while still being "stable" (never
  jittered, identical text every time they appear).

Usage
-----
    python scripts/generate_ocr_noise_fixture.py OUTPUT_DIR
        [--seed SEED] [--num-frames N]

Writes ``OUTPUT_DIR/frame-00.png`` .. ``frame-NN.png`` and
``OUTPUT_DIR/ground_truth.json`` (conforming to
``panoscribe.eval.models.GroundTruth``).

Determinism
-----------
All randomness is drawn from ``numpy.random.default_rng(seed)`` -- no global
RNG state is touched. Two runs with the same ``seed``/``num_frames`` produce
byte-identical *decoded* frame arrays (see ``generate_frames``). PNG-encoded
bytes are not asserted byte-identical across zlib versions; the fixture's
reproducibility claim is about the decoded pixel data, which is what OCR
actually consumes.
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
_OVERLAY_SKIP_FRAME_INDICES = frozenset({2, 7})


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
                (40, 420),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.1,
                (0, 0, 0),
                2,
                cv2.LINE_AA,
            )

        frames.append(frame)

    gt_dict: dict[str, object] = {
        "language": "en",
        "expected_texts": [
            {
                "text": _OVERLAY_TEXT,
                "start": 0.0,
                "end": float(num_frames),
                "required": True,
            }
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=str, help="Directory to write frames + GT into.")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--num-frames", type=int, default=_DEFAULT_NUM_FRAMES)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    write_fixture(Path(args.output_dir), num_frames=args.num_frames, seed=args.seed)
    print(f"Wrote {args.num_frames} frames + ground_truth.json to {args.output_dir}")


if __name__ == "__main__":
    main()
