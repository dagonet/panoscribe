"""Real-Whisper end-to-end test.

Every other test in this suite mocks ``faster_whisper`` at the boundary, so
none of them exercises model loading, the CPU/CUDA device shim, or the
actual audio decode path. This test drives a real ``WhisperTranscriber``
against a committed real-speech fixture (see ``tests/fixtures/e2e/README.md``
for provenance) on CPU with the ``tiny`` model, and is marked ``slow`` so it
never runs in the default suite (see ``pyproject.toml`` addopts).

Run locally with: ``uv run pytest -m slow -v``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from panoscribe.asr.whisper import WhisperTranscriber
from panoscribe.config import PanoScribeConfig

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "e2e" / "quick_brown_fox.wav"
# Actual clip duration is ~3.32s; give headroom for encoder rounding.
FIXTURE_DURATION_S = 3.4


@pytest.fixture
def cpu_tiny_config(monkeypatch: pytest.MonkeyPatch) -> PanoScribeConfig:
    """Config forcing CPU + the ``tiny`` model, bypassing the CUDA-only default."""
    monkeypatch.setenv("PANO_WHISPER_MODEL", "tiny")
    monkeypatch.setenv("PANO_WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("PANO_WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.delenv("PANO_WHISPER_LANGUAGE", raising=False)
    return PanoScribeConfig()


@pytest.mark.slow
def test_real_transcription_produces_valid_segments(cpu_tiny_config: PanoScribeConfig) -> None:
    """Real faster-whisper transcription over a real-speech clip.

    Assertions are restricted to properties robust to model nondeterminism
    (segment shape, timing, and the ASR/OCR field split) — never an exact
    transcript string, since the ``tiny`` model's exact wording can vary
    across faster-whisper/ctranslate2 versions.
    """
    transcriber = WhisperTranscriber(cpu_tiny_config)

    segments, detected_language = transcriber.transcribe(FIXTURE_PATH)

    assert len(segments) >= 1
    assert detected_language

    full_text = " ".join(s.text for s in segments).lower()
    assert full_text.strip() != ""
    # Loose keyword check against the known utterance — not an exact match.
    assert any(word in full_text for word in ("quick", "brown", "fox", "dog"))

    previous_end = 0.0
    for segment in segments:
        assert segment.start >= previous_end - 1e-6
        assert segment.end >= segment.start
        assert segment.end <= FIXTURE_DURATION_S + 1.0  # tolerance for trailing silence
        assert segment.text.strip() != ""
        # Post-#101 field split: ASR populates asr_logprob only.
        assert segment.asr_logprob is not None
        assert segment.asr_logprob < 0.0
        assert segment.ocr_confidence is None
        previous_end = segment.end


# The "bad model name fails loudly" property was verified manually rather than
# committed as a permanent suite test (see the coder log / PR description for
# the transcript of that run): a bogus ``PANO_WHISPER_MODEL`` attempts a
# network lookup against the Hugging Face Hub, so its failure mode/latency is
# environment-dependent (network present vs. absent) and would make the
# nightly CI job flaky rather than a reliable regression check.
