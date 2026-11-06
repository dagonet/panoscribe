"""Split a long PCM WAV into upload-sized chunks, cutting at quiet points.

Standard library only (``wave``, ``array``). The source is read in blocks and
each chunk is written straight to disk, so memory stays near one block, not
the whole recording.
"""

from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass
from itertools import accumulate
from typing import TYPE_CHECKING

from panoscribe.errors import PanoScribeError

if TYPE_CHECKING:
    from pathlib import Path

# A cut is placed in the quietest window of the last ``_SEARCH_S`` seconds that
# a chunk may still cover, so words are rarely cut in half.
_SEARCH_S = 10.0
_WINDOW_S = 0.1
# Servers refuse very short clips, so no chunk is made shorter than this
# (unless the configured limit itself leaves no room).
_MIN_CHUNK_S = 1.0
_WAV_HEADER_BYTES = 44
_COPY_BLOCK_FRAMES = 1 << 16
_SETTING = "PANO_ASR_REMOTE_MAX_UPLOAD_MB"


@dataclass(frozen=True)
class AudioChunk:
    """One piece of audio and where it starts in the source recording."""

    path: Path
    start_s: float


def split_wav(audio_path: Path, *, max_bytes: int, out_dir: Path) -> list[AudioChunk]:
    """Split ``audio_path`` so every file is at most ``max_bytes`` long.

    Returns ``[]`` for a WAV with no audio frames, and the original file as a
    single chunk when it already fits (``out_dir`` is then not created).
    Chunks are contiguous and non-overlapping, so every source frame appears
    exactly once.

    Raises:
        PanoScribeError: the input is not a 16-bit PCM WAV, or ``max_bytes``
            leaves room for less than one second of audio.
    """
    try:
        reader = wave.open(str(audio_path), "rb")  # noqa: SIM115 - closed in finally below
    except (wave.Error, EOFError):
        raise PanoScribeError(f"Cannot split {audio_path.name}: not a readable WAV file") from None
    try:
        return _split(reader, audio_path, max_bytes=max_bytes, out_dir=out_dir)
    except (wave.Error, EOFError):
        raise PanoScribeError(f"Cannot split {audio_path.name}: damaged WAV file") from None
    finally:
        reader.close()


def _split(
    reader: wave.Wave_read, audio_path: Path, *, max_bytes: int, out_dir: Path
) -> list[AudioChunk]:
    if reader.getsampwidth() != 2:
        raise PanoScribeError(
            f"Cannot split {audio_path.name}: only 16-bit PCM WAV is supported "
            f"(got {reader.getsampwidth() * 8}-bit)"
        )
    total = reader.getnframes()
    if total == 0:
        return []
    if audio_path.stat().st_size <= max_bytes:
        return [AudioChunk(audio_path, 0.0)]

    rate = reader.getframerate()
    frame_size = reader.getnchannels() * 2
    min_frames = int(_MIN_CHUNK_S * rate)
    max_frames = (max_bytes - _WAV_HEADER_BYTES) // frame_size
    if max_frames < min_frames:
        raise PanoScribeError(
            f"The upload limit is too small to split audio: it must leave room for at least "
            f"{_MIN_CHUNK_S:g} s of audio. Raise {_SETTING}."
        )
    window = max(1, int(_WINDOW_S * rate))
    search = int(_SEARCH_S * rate)

    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[AudioChunk] = []
    pos = 0
    while total - pos > max_frames:
        latest = min(pos + max_frames, total - min_frames)
        latest = max(latest, pos + min_frames)
        earliest = max(pos + min_frames, latest - search)
        cut = _quietest_cut(reader, earliest, latest, window)
        chunks.append(
            _write_chunk(reader, pos, cut, out_dir / f"chunk-{len(chunks):04d}.wav", rate)
        )
        pos = cut
    chunks.append(_write_chunk(reader, pos, total, out_dir / f"chunk-{len(chunks):04d}.wav", rate))
    return chunks


def _quietest_cut(reader: wave.Wave_read, earliest: int, latest: int, window: int) -> int:
    """Return the frame index at the middle of the quietest window in the range.

    Ties go to the latest window, which keeps chunks as full as possible. A
    range narrower than one window is cut at ``latest``.
    """
    if latest - earliest < window:
        return latest
    reader.setpos(earliest)
    data = reader.readframes(latest - earliest)
    if len(data) < (latest - earliest) * reader.getnchannels() * 2:
        raise PanoScribeError("WAV file ended before its declared length")
    samples = array("h", data)
    if sys.byteorder == "big":
        samples.byteswap()
    channels = reader.getnchannels()
    # Prefix sums of squares over interleaved samples; one window of frames is
    # ``window * channels`` consecutive samples.
    prefix = [0, *accumulate(s * s for s in samples)]
    span = window * channels
    best_start = 0
    best_energy: int | None = None
    for start in range(0, (latest - earliest) - window + 1):
        energy = prefix[start * channels + span] - prefix[start * channels]
        if best_energy is None or energy <= best_energy:
            best_energy = energy
            best_start = start
    return earliest + best_start + window // 2


def _write_chunk(reader: wave.Wave_read, start: int, end: int, path: Path, rate: int) -> AudioChunk:
    """Copy frames ``[start, end)`` to ``path`` in blocks."""
    reader.setpos(start)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(reader.getnchannels())
        writer.setsampwidth(2)
        writer.setframerate(rate)
        remaining = end - start
        while remaining > 0:
            block = reader.readframes(min(_COPY_BLOCK_FRAMES, remaining))
            if not block:
                raise PanoScribeError("WAV file ended before its declared length")
            writer.writeframes(block)
            remaining -= len(block) // (reader.getnchannels() * 2)
    return AudioChunk(path, start / rate)
