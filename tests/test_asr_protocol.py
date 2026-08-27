"""Tests for the AsrEngine protocol.

``AsrEngine`` is a structural (duck) protocol — any class with the right
method satisfies ``isinstance(engine, AsrEngine)``.
"""

from __future__ import annotations

from pathlib import Path


def test_whisper_transcriber_satisfies_protocol() -> None:
    """WhisperTranscriber with a cpu config must satisfy AsrEngine.

    Uses a cpu config (mirrors tests/test_whisper.py:19) so construction
    stays safe without touching the PR 2 CUDA probe — this test never calls
    ``transcribe``, so the probe (which lives inside ``_ensure_loaded``)
    never fires regardless, but a cpu config keeps that true even if
    ``_ensure_loaded`` behavior changes later.
    """
    from panoscribe.asr.protocol import AsrEngine
    from panoscribe.asr.whisper import WhisperTranscriber
    from panoscribe.config import PanoScribeConfig

    engine = WhisperTranscriber(PanoScribeConfig(whisper_device="cpu", whisper_compute_type="int8"))
    assert isinstance(engine, AsrEngine)


def test_fake_with_full_surface_satisfies_protocol() -> None:
    """A minimal class with the right method signature passes isinstance."""
    from panoscribe.asr.protocol import AsrEngine

    class _FakeEngine:
        def transcribe(self, audio_path: Path) -> tuple[list, str]:
            return [], "en"

    assert isinstance(_FakeEngine(), AsrEngine)


def test_fake_missing_method_fails_isinstance() -> None:
    """A class missing ``transcribe`` must NOT pass isinstance."""
    from panoscribe.asr.protocol import AsrEngine

    class _MissingTranscribe:
        pass

    assert not isinstance(_MissingTranscribe(), AsrEngine)
