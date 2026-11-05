"""Remote speech-to-text engine for generic OpenAI-compatible endpoints.

Opt-in: the pipeline builds this engine only when ``PANO_ASR_BACKEND=remote``.
It POSTs audio to ``{base_url}/audio/transcriptions`` and maps the
``verbose_json`` segments to :class:`~panoscribe.output.TranscriptSegment`.

Secrets: the API key is read here and nowhere else (``get_secret_value``). It
is never logged, never placed in an error message, and ``httpx`` exception
text (which can quote headers) is never used. Errors are raised outside the
``except`` block that caught the original, so neither ``__cause__`` nor
``__context__`` carries the request or the response body.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import random
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from panoscribe.asr.wav_split import AudioChunk, split_wav
from panoscribe.errors import PanoScribeError
from panoscribe.output import TranscriptSegment

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import httpx

    from panoscribe.config import PanoScribeConfig

logger = logging.getLogger(__name__)

# Held back from the configured upload limit for the multipart framing around
# the audio, so a whole request body stays inside the limit.
_REQUEST_OVERHEAD_BYTES = 4096
_CONNECT_TIMEOUT_S = 10.0
_CHUNK_DIR_NAME = "remote_asr_chunks"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_S = 1.0
_BACKOFF_CAP_S = 60.0
_NUMERIC_SECONDS = re.compile(r"\d+(?:\.\d+)?")

# Hosts already announced in this process: the engine is built once per video
# or API job, but the notice should appear once per host. Tests clear it.
_announced_hosts: set[str] = set()

# Whisper's language set: English name -> code.
_LANGUAGE_NAMES: dict[str, str] = {
    "english": "en",
    "chinese": "zh",
    "german": "de",
    "spanish": "es",
    "russian": "ru",
    "korean": "ko",
    "french": "fr",
    "japanese": "ja",
    "portuguese": "pt",
    "turkish": "tr",
    "polish": "pl",
    "catalan": "ca",
    "dutch": "nl",
    "arabic": "ar",
    "swedish": "sv",
    "italian": "it",
    "indonesian": "id",
    "hindi": "hi",
    "finnish": "fi",
    "vietnamese": "vi",
    "hebrew": "he",
    "ukrainian": "uk",
    "greek": "el",
    "malay": "ms",
    "czech": "cs",
    "romanian": "ro",
    "danish": "da",
    "hungarian": "hu",
    "tamil": "ta",
    "norwegian": "no",
    "thai": "th",
    "urdu": "ur",
    "croatian": "hr",
    "bulgarian": "bg",
    "lithuanian": "lt",
    "latin": "la",
    "maori": "mi",
    "malayalam": "ml",
    "welsh": "cy",
    "slovak": "sk",
    "telugu": "te",
    "persian": "fa",
    "latvian": "lv",
    "bengali": "bn",
    "serbian": "sr",
    "azerbaijani": "az",
    "slovenian": "sl",
    "kannada": "kn",
    "estonian": "et",
    "macedonian": "mk",
    "breton": "br",
    "basque": "eu",
    "icelandic": "is",
    "armenian": "hy",
    "nepali": "ne",
    "mongolian": "mn",
    "bosnian": "bs",
    "kazakh": "kk",
    "albanian": "sq",
    "swahili": "sw",
    "galician": "gl",
    "marathi": "mr",
    "punjabi": "pa",
    "sinhala": "si",
    "khmer": "km",
    "shona": "sn",
    "yoruba": "yo",
    "somali": "so",
    "afrikaans": "af",
    "occitan": "oc",
    "georgian": "ka",
    "belarusian": "be",
    "tajik": "tg",
    "sindhi": "sd",
    "gujarati": "gu",
    "amharic": "am",
    "yiddish": "yi",
    "lao": "lo",
    "uzbek": "uz",
    "faroese": "fo",
    "haitian creole": "ht",
    "pashto": "ps",
    "turkmen": "tk",
    "nynorsk": "nn",
    "maltese": "mt",
    "sanskrit": "sa",
    "luxembourgish": "lb",
    "myanmar": "my",
    "tibetan": "bo",
    "tagalog": "tl",
    "malagasy": "mg",
    "assamese": "as",
    "tatar": "tt",
    "hawaiian": "haw",
    "lingala": "ln",
    "hausa": "ha",
    "bashkir": "ba",
    "javanese": "jw",
    "sundanese": "su",
    "cantonese": "yue",
    # Aliases Whisper itself accepts.
    "burmese": "my",
    "valencian": "ca",
    "flemish": "nl",
    "haitian": "ht",
    "letzeburgesch": "lb",
    "pushto": "ps",
    "panjabi": "pa",
    "moldavian": "ro",
    "moldovan": "ro",
    "sinhalese": "si",
    "castilian": "es",
}
_LANGUAGE_CODES: frozenset[str] = frozenset(_LANGUAGE_NAMES.values())
_DEFAULT_LANGUAGE = "en"


def _normalise_language(value: object, fallback: str | None) -> str:
    """Return an ISO-style language code for a ``verbose_json`` ``language``.

    A two-letter code passes through lowercased (a region suffix such as
    ``zh-CN`` is dropped), a known English language name maps to its code.
    Anything else logs a warning and falls back to ``fallback``, then ``"en"``.
    """
    if isinstance(value, str):
        text = value.strip().lower()
        base = re.split(r"[-_]", text, maxsplit=1)[0]
        if len(base) == 2 and base.isalpha():
            return base
        if text in _LANGUAGE_NAMES:
            return _LANGUAGE_NAMES[text]
        if base in _LANGUAGE_CODES:
            return base
        logger.warning(
            "Remote ASR reported an unrecognised language (%.40r); using the fallback", text
        )
    elif value is not None:
        logger.warning(
            "Remote ASR reported an unrecognised language (a %s, not text); using the fallback",
            type(value).__name__,
        )
    if fallback and fallback.strip():
        return fallback.strip().lower()
    return _DEFAULT_LANGUAGE


def _is_loopback(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _checked_host(base_url: str) -> tuple[str, str]:
    """Validate ``base_url`` and return ``(scheme, hostname)``.

    Refuses user-info, a query string, a fragment, whitespace and anything but
    ``http``/``https`` with a host. The message never echoes the URL: it may
    carry a credential.
    """
    problem = (
        "PANO_ASR_REMOTE_BASE_URL must be an http or https URL with a host, and no "
        "user-info, query string or fragment (the value is not shown)"
    )
    if any(c.isspace() or not c.isprintable() for c in base_url) or "?" in base_url:
        raise PanoScribeError(problem)
    if "#" in base_url:
        raise PanoScribeError(problem)
    # The failure is recorded and raised outside the ``except`` so that no
    # ``__context__`` is left behind: the ValueError text quotes part of the URL.
    unparseable = False
    parts = None
    hostname = None
    try:
        parts = urlsplit(base_url)
        hostname = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        unparseable = True
    if unparseable or parts is None:
        raise PanoScribeError(problem)
    if (
        parts.scheme not in ("http", "https")
        or not hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise PanoScribeError(problem)
    return parts.scheme, hostname


class RemoteTranscriber:
    """:class:`~panoscribe.asr.protocol.AsrEngine` backed by an HTTP endpoint."""

    def __init__(
        self,
        config: PanoScribeConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if config.whisper_task == "translate":
            raise PanoScribeError(
                "Remote speech recognition does not support translate "
                "(PANO_WHISPER_TASK=translate / --translate). Use the local backend."
            )
        if not config.asr_remote_base_url:
            raise PanoScribeError(
                "Remote speech recognition needs PANO_ASR_REMOTE_BASE_URL (for example "
                "https://host/v1)."
            )
        if not config.asr_remote_model:
            raise PanoScribeError("Remote speech recognition needs PANO_ASR_REMOTE_MODEL.")
        scheme, hostname = _checked_host(config.asr_remote_base_url)
        key = config.asr_remote_api_key.get_secret_value() if config.asr_remote_api_key else ""
        if not all(33 <= ord(c) <= 126 for c in key):
            raise PanoScribeError(
                "PANO_ASR_REMOTE_API_KEY must be printable ASCII without whitespace "
                "(the value is not shown)."
            )
        try:
            import httpx as httpx_module
        except ImportError:
            httpx_module = None  # type: ignore[assignment]
        if httpx_module is None:
            raise PanoScribeError(
                "Remote speech recognition needs the httpx package. "
                "Install it with: uv sync --extra remote-asr"
            )

        # httpx logs every request URL at INFO, and a token in a URL path cannot
        # be recognised, so keep that logger quiet whenever this engine is built.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self._config = config
        self._httpx = httpx_module
        self._transport = transport
        self._sleep = sleep
        self._model: str = config.asr_remote_model
        self._url = f"{config.asr_remote_base_url.rstrip('/')}/audio/transcriptions"
        self._host = f"[{hostname}]" if ":" in hostname else hostname
        # A loopback server must not be reached through an environment proxy:
        # the proxy would receive the audio and the Authorization header.
        self._trust_env = not _is_loopback(hostname)
        self._announce(scheme, hostname)

    def _announce(self, scheme: str, hostname: str) -> None:
        """Log, once per host per process, that audio leaves the machine."""
        if self._host in _announced_hosts:
            return
        _announced_hosts.add(self._host)
        note = ""
        if scheme == "http" and not _is_loopback(hostname):
            note = " The connection is unencrypted (http): audio and any API key travel in clear."
        logger.warning(
            "Remote speech recognition is on: audio is being sent to %s.%s", self._host, note
        )

    def transcribe(self, audio_path: Path) -> tuple[list[TranscriptSegment], str]:
        """Transcribe ``audio_path`` remotely; return (segments, language).

        Audio over the upload limit is split at quiet points and sent one chunk
        at a time, in order. Any failing chunk fails the whole run.
        """
        cfg = self._config
        max_bytes = int(cfg.asr_remote_max_upload_mb * 1_000_000) - _REQUEST_OVERHEAD_BYTES
        chunks = split_wav(
            audio_path, max_bytes=max_bytes, out_dir=audio_path.parent / _CHUNK_DIR_NAME
        )
        language: str | None = None
        segments: list[TranscriptSegment] = []
        with self._new_client() as client:
            for chunk in chunks:
                body = self._post_chunk(client, chunk)
                parsed = self._parse_segments(body)
                if parsed and language is None:
                    language = _normalise_language(body.get("language"), cfg.whisper_language)
                segments.extend(
                    (start + chunk.start_s, end + chunk.start_s, text, logprob)
                    for start, end, text, logprob in parsed
                )
        final_language = language or _normalise_language(None, cfg.whisper_language)
        return [
            TranscriptSegment(
                start=start, end=end, text=text, asr_logprob=logprob, language=final_language
            )
            for start, end, text, logprob in segments
        ], final_language

    def _new_client(self) -> httpx.Client:
        """Build the HTTP client; any failure becomes a clear, chain-free error.

        Odd base URLs, proxy variables and ``SSL_CERT_FILE`` can all make httpx
        raise, with text that may quote them, so only the exception type is kept.
        """
        failure = ""
        client: httpx.Client | None = None
        try:
            client = self._httpx.Client(
                transport=self._transport,
                timeout=self._httpx.Timeout(
                    self._config.asr_remote_timeout_s, connect=_CONNECT_TIMEOUT_S
                ),
                follow_redirects=False,
                trust_env=self._trust_env,
            )
        except Exception as exc:
            failure = type(exc).__name__
        if client is None:
            raise PanoScribeError(
                f"Remote speech recognition could not set up its HTTP client ({failure}). "
                "Check the base URL (PANO_ASR_REMOTE_BASE_URL) and the proxy settings."
            )
        return client

    def _post_chunk(self, client: httpx.Client, chunk: AudioChunk) -> dict[str, object]:
        """POST one chunk and return the decoded JSON object."""
        cfg = self._config
        form: dict[str, str | list[str]] = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["segment"],
        }
        if cfg.whisper_language:
            form["language"] = cfg.whisper_language
        headers: dict[str, str] = {}
        if cfg.asr_remote_api_key and (key := cfg.asr_remote_api_key.get_secret_value()):
            headers["Authorization"] = f"Bearer {key}"
        # Bytes, not a file handle: every attempt sends the whole audio again.
        audio = chunk.path.read_bytes()
        attempts = cfg.asr_remote_max_retries + 1
        response: httpx.Response | None = None
        # Every failure is recorded inside the ``except`` and raised after it, so
        # the error has no ``__context__``: the original exception can hold the
        # request (with the Authorization header) or the response body.
        for attempt in range(attempts):
            failure: str
            fatal = False
            response = None
            try:
                response = client.post(
                    self._url,
                    data=form,
                    files={"file": (chunk.path.name, audio, "audio/wav")},
                    headers=headers,
                )
            except self._httpx.TransportError as exc:
                failure = type(exc).__name__
            except Exception as exc:
                failure = type(exc).__name__
                fatal = True
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    break
                failure = f"HTTP {response.status_code}"
            if fatal:
                raise PanoScribeError(
                    f"Remote speech recognition request to {self._host} failed ({failure})."
                )
            if attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After") if response else None
                self._sleep(_retry_delay(attempt, retry_after))
                continue
            raise PanoScribeError(
                f"Remote speech recognition at {self._host} failed ({failure}) after "
                f"{attempts} attempt(s) (model {self._model!r})."
            )
        if response is None:  # pragma: no cover - the loop always breaks or raises
            raise PanoScribeError(f"Remote speech recognition at {self._host} failed.")
        self._raise_for_status(response.status_code)
        body: object = None
        undecodable = False
        try:
            body = response.json()
        except (ValueError, RecursionError):
            undecodable = True
        if undecodable:
            raise PanoScribeError(
                f"Remote speech recognition at {self._host} returned a response that is "
                "not valid JSON."
            )
        if not isinstance(body, dict):
            raise PanoScribeError(
                f"Remote speech recognition at {self._host} returned an unexpected JSON response."
            )
        return body

    def _raise_for_status(self, status: int) -> None:
        """Raise a specific, non-retryable error for a non-2xx ``status``.

        Messages carry the host, the status and the configured model only; never
        the response body, headers, key or URL.
        """
        if 200 <= status < 300:
            return
        where = f"Remote speech recognition at {self._host}"
        if status in (401, 403):
            message = (
                f"{where} rejected the credentials (HTTP {status}). Check PANO_ASR_REMOTE_API_KEY."
            )
        elif status == 413:
            message = (
                f"{where} refused the upload as too large (HTTP 413). "
                "Lower PANO_ASR_REMOTE_MAX_UPLOAD_MB."
            )
        elif status == 400:
            message = (
                f"{where} rejected the request (HTTP 400) for model {self._model!r}. This "
                "backend needs a model that returns verbose_json with segment timestamps, "
                "such as a whisper-1 style model."
            )
        elif 300 <= status < 400:
            message = (
                f"{where} answered with a redirect (HTTP {status}), which is not followed. "
                "Check the base URL (PANO_ASR_REMOTE_BASE_URL)."
            )
        else:
            message = f"{where} failed with HTTP {status} (model {self._model!r})."
        raise PanoScribeError(message)

    def _no_timestamps(self) -> PanoScribeError:
        return PanoScribeError(
            f"The model {self._model!r} returned no segment timestamps, so it cannot be used "
            "for transcription here. Use a model that returns verbose_json with segment "
            "timestamps, such as a whisper-1 style model."
        )

    def _malformed(self) -> PanoScribeError:
        return PanoScribeError(
            f"The model {self._model!r} returned malformed segments (a negative or reversed "
            "timestamp, or text that is missing or not a string), so the result cannot be "
            "trusted. Nothing was repaired or dropped."
        )

    def _parse_segments(
        self, body: dict[str, object]
    ) -> list[tuple[float, float, str, float | None]]:
        """Return ``(start, end, text, logprob)`` per usable segment of one response."""
        raw = body.get("segments")
        if not isinstance(raw, list):
            raise self._no_timestamps()
        if not raw:
            text = body.get("text")
            if text is None:
                return []  # silence
            if not isinstance(text, str):
                raise self._malformed()
            if text.strip():
                raise self._no_timestamps()
            return []  # silence
        parsed: list[tuple[float, float, str, float | None]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise self._no_timestamps()
            start, end = item.get("start"), item.get("end")
            if not (_is_finite_number(start) and _is_finite_number(end)):
                raise self._no_timestamps()
            # Bad values are never clamped or dropped: they would invent timing.
            text_value = item.get("text")
            if start < 0 or end < start or not isinstance(text_value, str):  # type: ignore[operator]
                raise self._malformed()
            text = text_value.strip()
            if not text:
                continue
            logprob = item.get("avg_logprob")
            parsed.append(
                (
                    float(start),  # type: ignore[arg-type]
                    float(end),  # type: ignore[arg-type]
                    text,
                    float(logprob) if _is_finite_number(logprob) else None,  # type: ignore[arg-type]
                )
            )
        return parsed


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before retry number ``attempt + 1``.

    A numeric ``Retry-After`` is honoured, capped at 60 s. Otherwise the delay
    is exponential from 1 s with jitter: between the base step and twice it,
    never above the cap. An HTTP-date ``Retry-After`` falls back to backoff.
    """
    if retry_after is not None and _NUMERIC_SECONDS.fullmatch(retry_after.strip()):
        return min(float(retry_after), _BACKOFF_CAP_S)
    step = min(_BACKOFF_BASE_S * 2.0**attempt, _BACKOFF_CAP_S)
    return min(step * (1.0 + random.random()), _BACKOFF_CAP_S)


def _is_finite_number(value: object) -> bool:
    """True for a real, finite int or float (not a bool, NaN, infinity or a huge int)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large for a float
        return False
