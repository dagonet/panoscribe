"""ASR engine protocol — structural subtyping for swappable backends.

Uses :class:`typing.Protocol` (not ABC) so a future remote or alternative
transcription backend satisfies the interface by having the right method,
without needing to inherit from a base class.  Marked ``@runtime_checkable``
so ``isinstance(engine, AsrEngine)`` works at runtime.

The method signature mirrors :class:`panoscribe.asr.whisper.WhisperTranscriber`
exactly — every backend must expose:
* ``transcribe(audio_path)`` -> ``(segments, detected_language)``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from panoscribe.output import TranscriptSegment


@runtime_checkable
class AsrEngine(Protocol):
    """Structural protocol for ASR (speech-to-text) backends.

    Any object whose methods match this protocol — whether via inheritance,
    duck typing, or explicit implementation — is accepted as an ``AsrEngine``
    at runtime via ``isinstance(engine, AsrEngine)``.
    """

    def transcribe(self, audio_path: Path) -> tuple[list[TranscriptSegment], str]:
        """Run ASR on ``audio_path``; return (segments, detected_language)."""
        ...
