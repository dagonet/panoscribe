"""Tests for the stdlib WAV splitter used by the remote ASR backend."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from panoscribe.asr.wav_split import AudioChunk, split_wav
from panoscribe.errors import PanoScribeError

RATE = 16_000
# 18 s of 16 kHz mono 16-bit PCM plus the 44-byte header.
MAX = 44 + 18 * 32_000


def _wav(path: Path, segments: list[tuple[float, int]]) -> Path:
    """Write 16 kHz mono 16-bit PCM from ``(seconds, amplitude)`` pairs.

    Each segment alternates +amplitude/-amplitude, so any window inside it has
    exactly the same energy (ties are exact) and amplitude 0 is silence.
    """
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        for seconds, amp in segments:
            n = round(seconds * RATE)
            pair = struct.pack("<hh", amp, -amp)
            w.writeframes(pair * (n // 2) + (struct.pack("<h", amp) if n % 2 else b""))
    return path


def _read_frames(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


def _duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def test_within_limit_returns_original_and_writes_nothing(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(5, 9000)])
    out = tmp_path / "chunks"

    assert split_wav(src, max_bytes=MAX, out_dir=out) == [AudioChunk(src, 0.0)]
    assert not out.exists()


def test_header_only_wav_returns_empty(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [])
    out = tmp_path / "chunks"

    assert split_wav(src, max_bytes=MAX, out_dir=out) == []
    assert not out.exists()


def test_cuts_inside_quiet_gap(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(15, 9000), (1, 0), (15, 9000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) == 2
    assert 15.0 <= chunks[1].start_s <= 16.0


def test_chunks_fit_limit_and_preserve_every_frame(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(20, 3000), (0.5, 0), (20, 5000), (19.5, 7000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) >= 4
    assert all(c.path.stat().st_size <= MAX for c in chunks)
    assert b"".join(_read_frames(c.path) for c in chunks) == _read_frames(src)
    elapsed = 0.0
    for chunk in chunks:
        assert chunk.start_s == pytest.approx(elapsed)
        elapsed += _duration_s(chunk.path)
    assert elapsed == pytest.approx(_duration_s(src))
    assert chunks[0].start_s == 0.0


def test_just_over_limit_leaves_no_tiny_tail(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(18.2, 9000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) == 2
    assert _duration_s(chunks[-1].path) >= 1.0


def test_a_few_frames_over_limit_leaves_no_tiny_tail(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(18 + 5 / RATE, 9000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) == 2
    assert all(_duration_s(c.path) >= 1.0 for c in chunks)
    assert all(c.path.stat().st_size <= MAX for c in chunks)


def test_uniform_audio_cuts_at_latest_window(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(30, 9000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    # Tie on energy: the cut goes to the latest window, so the first chunk ends
    # within the last 100 ms of the allowed 18 s.
    assert 17.9 <= chunks[1].start_s <= 18.0


def test_limit_below_one_second_raises(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(5, 9000)])

    with pytest.raises(PanoScribeError, match="PANO_ASR_REMOTE_MAX_UPLOAD_MB"):
        split_wav(src, max_bytes=1000, out_dir=tmp_path / "c")


def test_limit_between_one_and_two_seconds_still_fits_every_chunk(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(4.5, 9000)])
    limit = 44 + int(1.5 * 32_000)

    chunks = split_wav(src, max_bytes=limit, out_dir=tmp_path / "c")

    assert all(c.path.stat().st_size <= limit for c in chunks)
    assert b"".join(_read_frames(c.path) for c in chunks) == _read_frames(src)


@pytest.mark.parametrize("bad", ["8-bit wav", "not a wav", "empty file"])
def test_unsupported_input_raises(tmp_path: Path, bad: str) -> None:
    src = tmp_path / "a.wav"
    if bad == "8-bit wav":
        with wave.open(str(src), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(RATE)
            w.writeframes(b"\x80" * 100)
    elif bad == "not a wav":
        src.write_bytes(b"this is definitely not a RIFF container")
    else:
        src.write_bytes(b"")

    with pytest.raises(PanoScribeError):
        split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")


def test_stereo_input_is_split_with_whole_frames(tmp_path: Path) -> None:
    src = tmp_path / "s.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<hh", 100, -100) * (RATE * 10))
    limit = 44 + 4 * RATE * 4  # 4 s of stereo

    chunks = split_wav(src, max_bytes=limit, out_dir=tmp_path / "c")

    assert len(chunks) == 3
    assert all(c.path.stat().st_size <= limit for c in chunks)
    assert b"".join(_read_frames(c.path) for c in chunks) == _read_frames(src)


def test_quieter_point_before_the_search_window_is_not_chosen(tmp_path: Path) -> None:
    # A silent second at 2-3 s is far quieter than anything else, but the first
    # cut may only look at the last 10 s a chunk can cover (8-18 s).
    src = _wav(tmp_path / "a.wav", [(2, 9000), (1, 0), (27, 9000)])

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) >= 2
    assert 8.0 <= chunks[1].start_s <= 18.0


def test_header_with_a_list_chunk_before_data(tmp_path: Path) -> None:
    """ffmpeg writes a 78-byte header (LIST/INFO before ``data``), not 44."""
    pcm = b"".join(struct.pack("<hh", amp, -amp) * (RATE // 2) for amp in range(100, 3100, 100))
    fmt = struct.pack("<HHIIHH", 1, 1, RATE, RATE * 2, 2, 16)
    info = b"INFO" + b"ISFT" + struct.pack("<I", 14) + b"Lavf58.76.100\x00"
    header = (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(info) + 8 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"LIST"
        + struct.pack("<I", len(info))
        + info
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    assert len(header) == 78
    src = tmp_path / "ffmpeg.wav"
    src.write_bytes(header + pcm)

    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")

    assert len(chunks) >= 2
    assert all(c.path.stat().st_size <= MAX for c in chunks)
    assert b"".join(_read_frames(c.path) for c in chunks) == pcm


def test_wav_shorter_than_its_header_declares_raises_clearly(tmp_path: Path) -> None:
    src = _wav(tmp_path / "a.wav", [(60, 9000)])
    src.write_bytes(src.read_bytes()[: 44 + 20 * 32_000])

    with pytest.raises(PanoScribeError, match="before its declared length"):
        split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")
