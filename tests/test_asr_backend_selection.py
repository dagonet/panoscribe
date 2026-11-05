"""Backend selection: the pipeline builds the engine the config asks for."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from panoscribe.config import PanoScribeConfig
from panoscribe.pipeline import _build_asr_engine, process_single_video

REMOTE_ENGINE = "panoscribe.asr.remote.RemoteTranscriber"
WHISPER = "panoscribe.pipeline.WhisperTranscriber"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [k for k in os.environ if k.startswith("PANO_")]:
        monkeypatch.delenv(name, raising=False)


def _cfg(tmp_path: Path, **over: object) -> PanoScribeConfig:
    values: dict[str, object] = {"temp_dir": tmp_path / "work", "ocr_enabled": False}
    values.update(over)
    return PanoScribeConfig(_env_file=None, **values)  # type: ignore[arg-type]


def _remote_cfg(tmp_path: Path) -> PanoScribeConfig:
    return _cfg(
        tmp_path,
        asr_backend="remote",
        asr_remote_base_url="https://asr.example.test/v1",
        asr_remote_model="whisper-1",
    )


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.transcribe.return_value = ([], "en")
    return engine


def test_default_builds_whisper(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    with patch(WHISPER) as whisper:
        engine = _build_asr_engine(cfg)

    whisper.assert_called_once_with(cfg)
    assert engine is whisper.return_value


def test_remote_builds_remote_not_whisper(tmp_path: Path) -> None:
    cfg = _remote_cfg(tmp_path)

    with patch(WHISPER) as whisper, patch(REMOTE_ENGINE) as remote:
        engine = _build_asr_engine(cfg)

    remote.assert_called_once_with(cfg)
    whisper.assert_not_called()
    assert engine is remote.return_value


def test_local_never_imports_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "panoscribe.asr.remote", raising=False)

    with patch(WHISPER):
        _build_asr_engine(_cfg(tmp_path))

    assert "panoscribe.asr.remote" not in sys.modules


def test_video_branch_uses_remote(tmp_path: Path) -> None:
    cfg = _remote_cfg(tmp_path)
    output = tmp_path / "out.json"
    engine = _fake_engine()

    with (
        patch("panoscribe.pipeline.download_video", return_value=tmp_path / "video.mp4"),
        patch("panoscribe.pipeline.extract_audio", return_value=tmp_path / "audio.wav"),
        patch(WHISPER) as whisper,
        patch(REMOTE_ENGINE, return_value=engine) as remote,
    ):
        process_single_video(
            "https://example.test/video", cfg, output, ocr_active=False, output_format="json"
        )

    remote.assert_called_once_with(cfg)
    engine.transcribe.assert_called_once_with(tmp_path / "audio.wav")
    whisper.assert_not_called()
    assert output.exists()


def test_photo_branch_uses_remote(tmp_path: Path) -> None:
    cfg = _remote_cfg(tmp_path)
    output = tmp_path / "out.json"
    engine = _fake_engine()
    post = SimpleNamespace(image_paths=[], audio_path=tmp_path / "sound.m4a")

    with (
        patch("panoscribe.pipeline.is_photo_post", return_value=True),
        patch("panoscribe.pipeline.download_photo_post", return_value=post),
        patch("panoscribe.pipeline.extract_audio", return_value=tmp_path / "audio.wav"),
        patch("panoscribe.pipeline.get_duration", return_value=3.0),
        patch(WHISPER) as whisper,
        patch(REMOTE_ENGINE, return_value=engine) as remote,
    ):
        process_single_video(
            "https://example.test/photo/1", cfg, output, ocr_active=False, output_format="json"
        )

    remote.assert_called_once_with(cfg)
    engine.transcribe.assert_called_once_with(tmp_path / "audio.wav")
    whisper.assert_not_called()
    assert output.exists()
