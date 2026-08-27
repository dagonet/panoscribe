"""Transcript data models and JSON writer."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

from panoscribe.errors import PanoScribeError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

# Soft cap: above this cross-product the merge warns but still runs.
# RapidFuzz handles ~1M comparisons in <1s; this surfaces pathological inputs
# rather than engineering for them.
_MERGE_SOFT_CAP: int = 5_000_000

# Collapse whitespace (including newlines) to a single space on [BOTH] emit
# so multi-line cues don't corrupt downstream format writers.
_WHITESPACE_RE = re.compile(r"\s+")


class TranscriptSegment(BaseModel):
    """A single transcript segment (speech or on-screen text).

    ``asr_logprob`` and ``ocr_confidence`` replace the former single
    ``confidence`` field, which conflated two incompatible scales. A
    single-source segment (``SPEECH`` or ``ON-SCREEN``) populates exactly
    one of the two; the other stays ``None``. A ``BOTH`` segment (see
    :func:`merge_channels`) inherits only ``asr_logprob`` from its speech
    side — the two scales are never combined.
    """

    start: float
    end: float
    text: str
    source: Literal["SPEECH", "ON-SCREEN", "BOTH"] = "SPEECH"
    asr_logprob: float | None = None
    """Raw Whisper ``avg_logprob`` for this segment: a negative float,
    roughly ``-3.0..0.0`` (closer to 0 is more confident), or ``None`` if
    unavailable. **Not a probability** — do not compare against
    ``ocr_confidence`` or treat as a [0, 1] score."""
    ocr_confidence: float | None = None
    """Mean pixel-match confidence from RapidOCR, in ``[0.0, 1.0]``
    (1.0 is most confident), or ``None`` for non-OCR segments."""
    language: str | None = None


class Transcript(BaseModel):
    """Full transcript: ordered segments plus detected language."""

    segments: list[TranscriptSegment]
    language: str


def write_json(transcript: Transcript, path: Path) -> None:
    """Write ``transcript`` as pretty JSON to ``path`` (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")


def write_txt(transcript: Transcript, path: Path) -> None:
    """Write ``transcript`` as plain text: one segment per line, UTF-8.

    No annotations, no timestamps, no source tags — just ``segment.text`` per
    line. Embedded ``\\n``/``\\r`` inside a segment are collapsed via
    :func:`_normalize_cue` so each segment occupies exactly one output line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_normalize_cue(s.text) for s in transcript.segments]
    # Trailing newline keeps editors/POSIX tools happy; empty transcript is "".
    body = "\n".join(lines)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def _format_srt_timestamp(seconds: float) -> str:
    """Render ``seconds`` as ``HH:MM:SS,mmm`` (SRT-standard comma separator).

    Handles fractional seconds by truncating the sub-millisecond tail. Hours
    are not capped at 99: transcripts rarely exceed that, so callers who feed
    day-long inputs can eyeball the result.
    """
    # Work in integer milliseconds to avoid float-repr "59.9999" artefacts.
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, millis = divmod(rem_ms, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(transcript: Transcript, path: Path) -> None:
    """Write ``transcript`` as SubRip (``.srt``) subtitles, UTF-8.

    Cues are 1-indexed. Timestamps use the SRT-standard
    ``HH:MM:SS,mmm --> HH:MM:SS,mmm`` form (comma separates the millisecond
    fraction). Cues are separated by a blank line; a trailing blank after the
    last cue is tolerated by every player surveyed and keeps the implementation
    branch-free.

    Embedded ``\\n``/``\\r`` in segment text are collapsed via
    :func:`_normalize_cue` because multi-line cue bodies can corrupt players
    that interpret the blank line as a cue boundary.

    HTML/angle-bracket escaping posture: **garbage-in-garbage-out.** Different
    SRT players render ``<`` / ``>`` either as literal characters or as
    tag markup; there is no portable escape. The caller controls cue content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cues: list[str] = []
    for idx, seg in enumerate(transcript.segments, start=1):
        start = _format_srt_timestamp(seg.start)
        end = _format_srt_timestamp(seg.end)
        body = _normalize_cue(seg.text)
        cues.append(f"{idx}\n{start} --> {end}\n{body}\n")
    path.write_text("\n".join(cues), encoding="utf-8")


def _format_mmss(seconds: float) -> str:
    """Render ``seconds`` as ``M:SS`` or ``MM:SS`` (no hour wrap).

    60 minutes → ``"60:00"`` rather than ``"1:00:00"``: short-form video
    timestamps read more naturally in minute-only form even for longer clips.
    Sub-second precision is **truncated** (not rounded): ``59.9 → "0:59"``.
    This matches ``int(seconds)`` floor semantics and keeps a segment's
    displayed start never ahead of its real start.
    """
    secs = int(seconds)
    minutes, rem = divmod(secs, 60)
    return f"{minutes}:{rem:02d}"


def _escape_markdown(text: str) -> str:
    """Escape ``|`` and ``` ` ``` so segment text can't corrupt tables/fences.

    Escape order: ``\\`` → ``\\\\`` first, then ``|`` → ``\\|`` and
    ``` ` ``` → ``\\` ``. A caller that pre-escapes (``\\|`` in the source
    text) will see it doubled on output. OCR and ASR outputs do not contain
    pre-escaped Markdown in practice; if a downstream consumer needs
    idempotent escaping, feed raw text in.
    """
    return text.replace("\\", "\\\\").replace("|", r"\|").replace("`", r"\`")


def write_markdown(transcript: Transcript, path: Path) -> None:
    """Write ``transcript`` as compact Markdown, UTF-8 — one line per segment.

    Format: ``**[{SOURCE}] {m:ss}-{m:ss}** {text}`` where the separator is a
    Unicode en-dash (U+2013), not an ASCII hyphen — chosen for typographic
    clarity between timestamps.

    No frontmatter, no title, no legend — downstream consumers can prepend
    their own. Pipe (``|``) and backtick (``` ` ```) are escaped in segment
    text to prevent table/code-fence corruption. Embedded newlines are
    collapsed via :func:`_normalize_cue`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for seg in transcript.segments:
        body = _escape_markdown(_normalize_cue(seg.text))
        start = _format_mmss(seg.start)
        end = _format_mmss(seg.end)
        lines.append(f"**[{seg.source}] {start}\u2013{end}** {body}")
    body = "\n".join(lines)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def write_transcript(transcript: Transcript, path: Path, fmt: str) -> None:
    """Dispatch ``transcript`` to the appropriate format writer by ``fmt``.

    Supported format values:
    ``"json"``, ``"txt"``, ``"srt"``, ``"md"`` (Markdown).

    Unknown ``fmt`` raises :class:`PanoScribeError`.
    """
    _writer_registry: dict[str, Callable[[Transcript, Path], None]] = {
        "json": write_json,
        "txt": write_txt,
        "srt": write_srt,
        "md": write_markdown,
    }
    writer = _writer_registry.get(fmt)
    if writer is None:
        raise PanoScribeError(f"Unknown output format: {fmt!r}")
    writer(transcript, path)


def _overlaps(speech: TranscriptSegment, ocr: TranscriptSegment) -> bool:
    """Inclusive temporal overlap: touching boundaries DO overlap.

    Two segments overlap iff ``speech.start <= ocr.end`` AND ``ocr.start <= speech.end``.
    Example: ``speech=[0.0, 5.0]`` and ``ocr=[5.0, 10.0]`` DO overlap.
    """
    return speech.start <= ocr.end and ocr.start <= speech.end


def _normalize_cue(text: str) -> str:
    """Collapse internal whitespace (incl. ``\\n``/``\\r``) to single spaces and strip."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def merge_channels(
    speech: list[TranscriptSegment],
    ocr: list[TranscriptSegment],
    threshold: float,
) -> list[TranscriptSegment]:
    """Cross-source dedup: collapse overlapping, text-similar speech+OCR into ``[BOTH]``.

    Algorithm
    ---------
    For each SPEECH segment, find all OCR segments that temporally overlap it
    (inclusive rule: ``speech.start <= ocr.end AND ocr.start <= speech.end`` —
    touching boundaries DO overlap). Among overlapping OCR segments,
    compute ``rapidfuzz.fuzz.WRatio(speech.text, ocr.text)`` (returns 0-100).
    Any OCR meeting ``WRatio >= threshold * 100`` is a candidate to collapse
    with the speech segment. Pick the candidate with the highest WRatio
    (ties → earliest ``ocr.start``) and emit::

        TranscriptSegment(
            source="BOTH",
            text=speech.text,                     # whitespace-normalized
            start=min(speech.start, ocr.start),
            end=max(speech.end, ocr.end),
            asr_logprob=speech.asr_logprob,       # OCR confidence is dropped
            language=speech.language,
        )

    The chosen OCR segment is **consumed**; other overlapping OCR segments
    stay as ``[ON-SCREEN]``. Each OCR segment collapses at most once.

    Trade-offs
    ----------
    * **Lossy on collapse.** The emitted ``text`` is ``speech.text`` even when
      the OCR segment holds richer detail (e.g. speech: "as I mentioned";
      OCR: "AcmeCloud Enterprise v4.2"). Concatenating OCR onto speech would
      produce awkward output; users who need the OCR detail can read the
      consumed OCR segment (currently dropped — revisit if users report loss).
    * **``asr_logprob=speech.asr_logprob``, ``ocr_confidence`` dropped.**
      Whisper's log-prob and RapidOCR's pixel-match score are on incompatible
      scales and are never combined. Since ``text`` is speech-sourced, only
      the speech-side field carries over; the consumed OCR segment's
      ``ocr_confidence`` is lost along with the rest of its content (see the
      lossy-on-collapse note above).
    * **Whitespace normalized.** The merged text has internal ``\\n``/``\\r``
      and consecutive spaces collapsed to single spaces so downstream format
      writers (SRT, MD) don't corrupt on multi-line cues.

    Parameters
    ----------
    speech:
        SPEECH segments (ASR output).
    ocr:
        ON-SCREEN segments (post-dedup OCR output).
    threshold:
        Similarity floor in ``[0.0, 1.0]`` — scaled by 100 before comparison
        with ``WRatio``. ``0.85`` is the default from
        ``PanoScribeConfig.merge_similarity_threshold``.

    Returns
    -------
    list[TranscriptSegment]
        Stable-sorted by ``start``; SPEECH-first on equal starts (because
        speech is appended before OCR prior to the stable sort).
    """
    if not speech and not ocr:
        return []
    if not speech:
        return list(ocr)
    if not ocr:
        return list(speech)

    # Soft cap — don't engineer for pathological inputs, just flag them.
    if len(speech) * len(ocr) > _MERGE_SOFT_CAP:
        logger.warning(
            "merge_channels cross-product exceeds soft cap "
            "(len(speech)=%d, len(ocr)=%d, product=%d > %d); proceeding",
            len(speech),
            len(ocr),
            len(speech) * len(ocr),
            _MERGE_SOFT_CAP,
        )

    score_cutoff = threshold * 100.0
    consumed_ocr_idx: set[int] = set()
    emitted: list[TranscriptSegment] = []

    for sp in speech:
        best_idx: int | None = None
        best_score: float = -1.0
        best_start: float | None = None
        for idx, oc in enumerate(ocr):
            if idx in consumed_ocr_idx:
                continue
            if not _overlaps(sp, oc):
                continue
            # ``processor=str.lower`` makes the comparison case-insensitive.
            # On-screen captions arrive uppercased (e.g. ``KEINE KAMPFSPORTTECHNIK``)
            # while ASR speech is mixed-case; without case folding ``WRatio``
            # scores the canonical pair near 15 instead of ~87 (Sprint OCR-Recall
            # Risk-2 finding).
            score = fuzz.WRatio(sp.text, oc.text, processor=str.lower)
            if score < score_cutoff:
                continue
            # Highest score wins; ties → earliest ocr.start. ``best_start`` is
            # None until the first candidate wins, so the first iteration never
            # hits the tie branch — avoids a sentinel-vs-real-0.0 collision.
            better = score > best_score or (
                score == best_score and best_start is not None and oc.start < best_start
            )
            if better:
                best_idx = idx
                best_score = score
                best_start = oc.start

        if best_idx is None:
            emitted.append(sp)
            continue

        oc = ocr[best_idx]
        consumed_ocr_idx.add(best_idx)
        emitted.append(
            TranscriptSegment(
                source="BOTH",
                text=_normalize_cue(sp.text),
                start=min(sp.start, oc.start),
                end=max(sp.end, oc.end),
                asr_logprob=sp.asr_logprob,
                language=sp.language,
            )
        )

    # Add OCR segments not consumed by any speech collapse.
    for idx, oc in enumerate(ocr):
        if idx not in consumed_ocr_idx:
            emitted.append(oc)

    # Stable sort by start — SPEECH/BOTH appended before unconsumed OCR keeps
    # speech-first ordering on equal starts (matches prior behavior).
    emitted.sort(key=lambda s: s.start)
    return emitted
