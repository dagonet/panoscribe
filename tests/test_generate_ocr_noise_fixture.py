"""Determinism tests for scripts/generate_ocr_noise_fixture.py.

CI-safe: pure numpy/cv2 array generation, no OCR model inference, no
external dependencies beyond the packages already required for the OCR
pipeline itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# scripts/ is not a package; import the module directly by path so this
# test does not require an editable/namespace-package install of scripts/.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from generate_ocr_noise_fixture import (  # noqa: E402
    _OVERLAY_SKIP_FRAME_INDICES,
    _OVERLAY_TEXT,
    generate_frames,
)


class TestGenerateFramesDeterminism:
    """Two runs with the same seed/num_frames must be byte-identical."""

    def test_same_seed_produces_identical_frame_arrays(self) -> None:
        fixture_a = generate_frames(num_frames=12, seed=42)
        fixture_b = generate_frames(num_frames=12, seed=42)

        assert len(fixture_a.frames) == len(fixture_b.frames) == 12
        for frame_a, frame_b in zip(fixture_a.frames, fixture_b.frames, strict=True):
            assert np.array_equal(frame_a, frame_b)

    def test_same_seed_produces_identical_ground_truth(self) -> None:
        fixture_a = generate_frames(num_frames=12, seed=42)
        fixture_b = generate_frames(num_frames=12, seed=42)
        assert fixture_a.ground_truth == fixture_b.ground_truth

    def test_different_seed_produces_different_jitter(self) -> None:
        fixture_a = generate_frames(num_frames=12, seed=42)
        fixture_b = generate_frames(num_frames=12, seed=7)
        # At least one frame must differ under a different seed -- otherwise
        # the RNG is not actually wired into the pixel output.
        any_diff = any(
            not np.array_equal(a, b)
            for a, b in zip(fixture_a.frames, fixture_b.frames, strict=True)
        )
        assert any_diff

    def test_does_not_mutate_global_numpy_random_state(self) -> None:
        np.random.seed(1234)
        before = np.random.get_state()[1].copy()
        generate_frames(num_frames=12, seed=42)
        after = np.random.get_state()[1]
        assert np.array_equal(before, after)


class TestGenerateFramesGroundTruth:
    """Ground-truth content matches the fixture's overlay-caption design."""

    def test_ground_truth_contains_only_the_overlay_caption(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        expected_texts = fixture.ground_truth["expected_texts"]
        assert len(expected_texts) == 1
        assert expected_texts[0]["text"] == _OVERLAY_TEXT
        assert expected_texts[0]["required"] is True

    def test_frame_count_matches_requested_num_frames(self) -> None:
        fixture = generate_frames(num_frames=5, seed=42)
        assert len(fixture.frames) == 5

    def test_overlay_skip_indices_are_within_frame_range(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        assert all(0 <= idx < len(fixture.frames) for idx in _OVERLAY_SKIP_FRAME_INDICES)
        # Overlay must be skipped in a strict minority of frames -- it must
        # stay the majority signal to be "stable" per the fixture design.
        assert len(_OVERLAY_SKIP_FRAME_INDICES) < len(fixture.frames) / 2
