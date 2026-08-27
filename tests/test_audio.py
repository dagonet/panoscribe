"""Unit tests for panoscribe.audio (all subprocess boundaries mocked)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from panoscribe.audio import extract_audio
from panoscribe.errors import PanoScribeError


def test_extract_audio_builds_correct_ffmpeg_argv(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    out = tmp_path / "out" / "audio.wav"

    with (
        patch("panoscribe.audio._FFMPEG", "/usr/bin/ffmpeg"),
        patch("panoscribe.audio.subprocess.run") as mock_run,
    ):
        result = extract_audio(video, out)

    assert result == out
    assert out.parent.is_dir()
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == [
        "/usr/bin/ffmpeg",
        "-i",
        str(video),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-vn",
        "-f",
        "wav",
        str(out),
        "-y",
    ]
    assert kwargs["check"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["shell"] is False


def test_extract_audio_raises_when_ffmpeg_missing(tmp_path: Path) -> None:
    with (
        patch("panoscribe.audio._FFMPEG", None),
        pytest.raises(PanoScribeError, match="ffmpeg not found"),
    ):
        extract_audio(tmp_path / "a.mp4", tmp_path / "b.wav")


def test_extract_audio_wraps_called_process_error(tmp_path: Path) -> None:
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr=b"line one\nline two: Invalid data found\n",
    )
    with (
        patch("panoscribe.audio._FFMPEG", "/usr/bin/ffmpeg"),
        patch("panoscribe.audio.subprocess.run", side_effect=err),
        pytest.raises(PanoScribeError, match="Invalid data found"),
    ):
        extract_audio(tmp_path / "a.mp4", tmp_path / "b.wav")


# -- get_duration -------------------------------------------------------------


def test_get_duration_parses_ffprobe(tmp_path: Path) -> None:
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")
    mock_stdout = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"13.35\n", stderr=b"")

    # shutil.which must be patched too: get_duration early-returns None when
    # ffprobe is absent from PATH, so on ffmpeg-less environments the
    # subprocess mock would never be reached.
    with (
        patch("panoscribe.audio.subprocess.run", return_value=mock_stdout),
        patch("panoscribe.audio.shutil.which", return_value="/usr/bin/ffprobe"),
    ):
        from panoscribe.audio import get_duration

        result = get_duration(audio)

    assert result == pytest.approx(13.35)


def test_get_duration_failure_returns_none(tmp_path: Path) -> None:
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")

    with (
        patch("panoscribe.audio.subprocess.run", side_effect=FileNotFoundError),
        patch("panoscribe.audio.shutil.which", return_value="/usr/bin/ffprobe"),
    ):
        from panoscribe.audio import get_duration

        result = get_duration(audio)

    assert result is None


def test_get_duration_ffprobe_missing_returns_none(tmp_path: Path) -> None:
    """ffprobe absent from PATH -> log warning + return None."""
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")

    with patch("panoscribe.audio.shutil.which", return_value=None):
        from panoscribe.audio import get_duration

        result = get_duration(audio)

    assert result is None


def test_get_duration_nonzero_exit_returns_none(tmp_path: Path) -> None:
    """ffprobe runs but exits non-zero -> log warning + return None."""
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")
    mock_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")

    with (
        patch("panoscribe.audio.subprocess.run", return_value=mock_proc),
        patch("panoscribe.audio.shutil.which", return_value="/usr/bin/ffprobe"),
    ):
        from panoscribe.audio import get_duration

        result = get_duration(audio)

    assert result is None


def test_get_duration_empty_output_returns_none(tmp_path: Path) -> None:
    """ffprobe returns 0 but stdout is empty -> log warning + return None."""
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")
    mock_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    with (
        patch("panoscribe.audio.subprocess.run", return_value=mock_proc),
        patch("panoscribe.audio.shutil.which", return_value="/usr/bin/ffprobe"),
    ):
        from panoscribe.audio import get_duration

        result = get_duration(audio)

    assert result is None


def test_extract_audio_called_process_error_no_stderr(tmp_path: Path) -> None:
    """CalledProcessError with empty stderr -> detail uses exit status."""
    err = subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"")
    with (
        patch("panoscribe.audio._FFMPEG", "/usr/bin/ffmpeg"),
        patch("panoscribe.audio.subprocess.run", side_effect=err),
        pytest.raises(PanoScribeError, match="exit status 1 with no stderr output"),
    ):
        extract_audio(tmp_path / "a.mp4", tmp_path / "b.wav")
