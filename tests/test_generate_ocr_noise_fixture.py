"""Determinism tests for scripts/generate_ocr_noise_fixture.py.

CI-safe: pure numpy/cv2 array generation, no OCR model inference, no
external dependencies beyond the packages already required for the OCR
pipeline itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# scripts/ is not a package; import the module directly by path so this
# test does not require an editable/namespace-package install of scripts/.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from generate_ocr_noise_fixture import (  # noqa: E402
    _ALL_CAPS_BG_TEXT,
    _CHROME_HANDLE_TEXT,
    _CHROME_SUBSCRIBE_TEXT,
    _LARGE_BG_TEXT,
    _LOWERCASE_OVERLAY_TEXT,
    _OVERLAY_SKIP_FRAME_INDICES,
    _OVERLAY_TEXT,
    _SHORT_LIVED_A_FRAME_INDICES,
    _SHORT_LIVED_A_TEXT,
    _SHORT_LIVED_B_FRAME_INDICES,
    _SHORT_LIVED_B_TEXT,
    _SHORT_LIVED_C_FRAME_INDICES,
    _SHORT_LIVED_C_TEXT,
    _STABLE_JUNK_TEXT,
    VIDEO_FILENAME,
    generate_frames,
    write_video_fixture,
)

cv2 = pytest.importorskip("cv2")


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

    def test_ground_truth_contains_the_required_overlays(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        expected_texts = fixture.ground_truth["expected_texts"]
        texts = {e["text"] for e in expected_texts}
        assert texts == {
            _OVERLAY_TEXT,
            _SHORT_LIVED_A_TEXT,
            _SHORT_LIVED_B_TEXT,
            _SHORT_LIVED_C_TEXT,
            _LOWERCASE_OVERLAY_TEXT,
        }
        assert all(e["required"] is True for e in expected_texts)

    def test_ground_truth_omits_stable_junk_and_chrome(self) -> None:
        """Stable junk and UI chrome are noise -- never listed in GT."""
        fixture = generate_frames(num_frames=12, seed=42)
        texts = {e["text"] for e in fixture.ground_truth["expected_texts"]}
        assert _STABLE_JUNK_TEXT not in texts
        assert _CHROME_SUBSCRIBE_TEXT not in texts
        assert _CHROME_HANDLE_TEXT not in texts

    def test_ground_truth_omits_typography_confound_junk(self) -> None:
        """Phase 3's ALL-CAPS and large background junk are never listed in GT."""
        fixture = generate_frames(num_frames=12, seed=42)
        texts = {e["text"] for e in fixture.ground_truth["expected_texts"]}
        assert _ALL_CAPS_BG_TEXT not in texts
        assert _LARGE_BG_TEXT not in texts

    def test_short_lived_c_has_exactly_its_declared_appearance(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        by_text = {e["text"]: e for e in fixture.ground_truth["expected_texts"]}
        c_appearances = by_text[_SHORT_LIVED_C_TEXT]["appearances"]
        assert {tuple(w) for w in c_appearances} == {
            (float(i), float(i)) for i in _SHORT_LIVED_C_FRAME_INDICES
        }

    def test_short_lived_overlays_have_exactly_their_declared_appearances(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        by_text = {e["text"]: e for e in fixture.ground_truth["expected_texts"]}

        a_appearances = by_text[_SHORT_LIVED_A_TEXT]["appearances"]
        assert {tuple(w) for w in a_appearances} == {
            (float(i), float(i)) for i in _SHORT_LIVED_A_FRAME_INDICES
        }
        assert len(a_appearances) == 1  # "1-2 sampled frames" -- this one is 1.

        b_appearances = by_text[_SHORT_LIVED_B_TEXT]["appearances"]
        assert {tuple(w) for w in b_appearances} == {
            (float(i), float(i)) for i in _SHORT_LIVED_B_FRAME_INDICES
        }
        assert len(b_appearances) == 2  # "1-2 sampled frames" -- this one is 2.

    def test_frame_count_matches_requested_num_frames(self) -> None:
        fixture = generate_frames(num_frames=5, seed=42)
        assert len(fixture.frames) == 5

    def test_overlay_skip_indices_are_within_frame_range(self) -> None:
        fixture = generate_frames(num_frames=12, seed=42)
        assert all(0 <= idx < len(fixture.frames) for idx in _OVERLAY_SKIP_FRAME_INDICES)
        # Overlay must be skipped in a strict minority of frames -- it must
        # stay the majority signal to be "stable" per the fixture design.
        assert len(_OVERLAY_SKIP_FRAME_INDICES) < len(fixture.frames) / 2


class TestWriteVideoFixtureDeterminism:
    """The video path must reproduce byte-identical decoded frames."""

    def test_lossless_roundtrip_matches_generated_arrays(self, tmp_path: Path) -> None:
        video_path = write_video_fixture(tmp_path, num_frames=6, seed=42, fps=1.0)
        assert video_path.name == VIDEO_FILENAME
        assert video_path.exists()

        expected = generate_frames(num_frames=6, seed=42).frames

        cap = cv2.VideoCapture(str(video_path))
        try:
            assert cap.isOpened()
            decoded: list[np.ndarray] = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                decoded.append(frame)
        finally:
            cap.release()

        assert len(decoded) == len(expected)
        for actual_frame, expected_frame in zip(decoded, expected, strict=True):
            assert np.array_equal(actual_frame, expected_frame)

    def test_two_runs_produce_byte_identical_video_files(self, tmp_path: Path) -> None:
        video_a = write_video_fixture(tmp_path / "a", num_frames=6, seed=42, fps=1.0)
        video_b = write_video_fixture(tmp_path / "b", num_frames=6, seed=42, fps=1.0)
        assert video_a.read_bytes() == video_b.read_bytes()

    def test_writes_ground_truth_alongside_video(self, tmp_path: Path) -> None:
        write_video_fixture(tmp_path, num_frames=6, seed=42, fps=1.0)
        gt_path = tmp_path / "ground_truth.json"
        assert gt_path.exists()
