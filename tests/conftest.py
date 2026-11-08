"""Shared pytest fixtures.

Patch targets live at the *import site*, e.g. ``panoscribe.acquire.downloader.YoutubeDL``,
never at the library's own module (``yt_dlp.YoutubeDL``). Patching at the import site
captures the bound name inside the module under test; patching at the library path leaves
the already-bound alias untouched and the real class still runs.
"""

from __future__ import annotations

import logging
import os
import sys
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Neutralize Rich's TTY-dependent styling before Typer imports. On GitHub Actions
# (``CI=true``/``GITHUB_ACTIONS=true``) Rich emits bold/dim escape codes *inside*
# quoted flag names, which breaks substring assertions in CLI tests (e.g.
# ``"--output"``, ``"Invalid value for '--platform'"``). ``NO_COLOR`` only
# disables color per no-color.org — bold/dim persist — so the reliable switch is
# ``TERM=dumb``, which Rich treats as a non-styling terminal. ``COLUMNS=200``
# stops panel borders from wrapping long flag names across lines. Must run at
# module import (before ``from panoscribe.cli import app``) because Rich caches
# terminal detection when the Typer app is first constructed.
os.environ["TERM"] = "dumb"
os.environ["COLUMNS"] = "200"

import pytest

from panoscribe.config import PanoScribeConfig


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PanoScribeConfig:
    monkeypatch.setenv("PANO_TEMP_DIR", str(tmp_path / "omni-tmp"))
    monkeypatch.delenv("PANO_WHISPER_LANGUAGE", raising=False)
    return PanoScribeConfig()


@pytest.fixture
def silence_wav_path(tmp_path: Path) -> Path:
    """1s 16 kHz mono PCM silence.

    Mock-only fixture — this file is byte-valid WAV but not exercised by real decoders
    in unit tests. Sprint 1.2 tests that exercise ffmpeg/faster-whisper must mock those
    boundaries, not decode this file.
    """
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return path


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Clear root logger handlers + level around each test (CliRunner isolation)."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    yield
    root.handlers.clear()
    root.handlers.extend(saved_handlers)
    root.level = saved_level


@pytest.fixture(autouse=True)
def restore_rapidocr_bidi_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo panoscribe's rapidocr bidi patch (#188) after every test.

    ``RapidOCREngine._ensure_loaded`` replaces ``reorder_bidi_for_display`` in rapidocr's
    recogniser module for the whole process. Re-setting the current value through
    ``monkeypatch`` puts the original back at teardown, so a test that built the engine
    does not leave rapidocr patched for the tests after it. Looked up in ``sys.modules``,
    so nothing new is imported (``panoscribe.ocr.rapid_ocr`` imports rapidocr already).
    """
    module = sys.modules.get("rapidocr.ch_ppocr_rec.main")
    if module is not None and hasattr(module, "reorder_bidi_for_display"):
        monkeypatch.setattr(module, "reorder_bidi_for_display", module.reorder_bidi_for_display)


@pytest.fixture
def mock_ollama_client() -> MagicMock:
    """Pre-shaped mock ``ollama.Client`` instance for LLM-cleanup tests.

    Defaults:
    - ``list()`` returns a ``SimpleNamespace`` with one model named
      ``llama3.2:3b`` (the config default); tests that assert model-presence-
      gate failure override ``.list.return_value``.
    - ``chat()`` returns the dict shape ollama-python emits:
      ``{"message": {"content": "cleaned text"}}``.

    Patch at the import site: ``panoscribe.merge.llm_cleanup.Client``.
    """
    mock = MagicMock()
    mock.list.return_value = SimpleNamespace(models=[SimpleNamespace(model="llama3.2:3b")])
    mock.chat.return_value = {"message": {"content": "cleaned text"}}
    return mock
