"""Tests for the remote OpenAI-compatible ASR engine (no network)."""

from __future__ import annotations

import logging
import os
import struct
import sys
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from panoscribe.asr import remote
from panoscribe.asr.protocol import AsrEngine
from panoscribe.asr.remote import RemoteTranscriber, _normalise_language
from panoscribe.config import PanoScribeConfig
from panoscribe.errors import PanoScribeError

RATE = 16_000
KEY = "sk-test-secret"
BASE = "https://asr.example.test/v1"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in [k for k in os.environ if k.startswith("PANO_")]:
        monkeypatch.delenv(name, raising=False)
    remote._announced_hosts.clear()
    yield
    remote._announced_hosts.clear()


def _cfg(**over: object) -> PanoScribeConfig:
    values: dict[str, object] = {
        "asr_backend": "remote",
        "asr_remote_base_url": BASE,
        "asr_remote_model": "whisper-1",
        "asr_remote_api_key": KEY,
    }
    values.update(over)
    return PanoScribeConfig(_env_file=None, **values)  # type: ignore[arg-type]


def _engine(handler: Handler, cfg: PanoScribeConfig | None = None) -> RemoteTranscriber:
    return RemoteTranscriber(
        cfg or _cfg(), transport=httpx.MockTransport(handler), sleep=lambda _s: None
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"language": "english", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]},
    )


def _write_wav(path: Path, seconds: float) -> Path:
    n = round(seconds * RATE)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<hh", 9000, -9000) * (n // 2))
    return path


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    return _write_wav(tmp_path / "audio.wav", 2.0)


def _json_handler(body: object, calls: list[httpx.Request] | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=body)

    return handler


def test_satisfies_protocol() -> None:
    assert isinstance(_engine(_ok), AsrEngine)


def test_request_shape(wav: Path) -> None:
    calls: list[httpx.Request] = []
    _engine(_json_handler({"language": "en", "segments": []}, calls)).transcribe(wav)

    (request,) = calls
    assert request.method == "POST"
    assert str(request.url) == "https://asr.example.test/v1/audio/transcriptions"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    body = request.content
    assert b'name="model"\r\n\r\nwhisper-1' in body
    assert b'name="response_format"\r\n\r\nverbose_json' in body
    assert b'name="timestamp_granularities[]"\r\n\r\nsegment' in body
    assert wav.read_bytes() in body
    assert b'name="language"' not in body


def test_language_sent_when_forced(wav: Path) -> None:
    calls: list[httpx.Request] = []
    cfg = _cfg(whisper_language="de")

    _engine(_json_handler({"segments": []}, calls), cfg).transcribe(wav)

    assert b'name="language"\r\n\r\nde' in calls[0].content


def test_no_auth_header_without_key(wav: Path) -> None:
    calls: list[httpx.Request] = []

    _engine(_json_handler({"segments": []}, calls), _cfg(asr_remote_api_key=None)).transcribe(wav)

    assert "Authorization" not in calls[0].headers


def test_trailing_slash_in_base_url_gives_single_slash(wav: Path) -> None:
    calls: list[httpx.Request] = []

    _engine(
        _json_handler({"segments": []}, calls), _cfg(asr_remote_base_url=BASE + "/")
    ).transcribe(wav)

    assert str(calls[0].url) == "https://asr.example.test/v1/audio/transcriptions"


def test_maps_segments(wav: Path) -> None:
    body = {
        "language": "en",
        "segments": [{"start": 1.0, "end": 2.5, "text": " hi ", "avg_logprob": -0.2}],
    }

    segments, language = _engine(_json_handler(body)).transcribe(wav)

    assert language == "en"
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.start, seg.end, seg.text, seg.asr_logprob, seg.language) == (
        1.0,
        2.5,
        "hi",
        -0.2,
        "en",
    )
    assert seg.source == "SPEECH"


def test_full_language_name_is_normalised(wav: Path) -> None:
    body = {"language": "german", "segments": [{"start": 0, "end": 1, "text": "hallo"}]}

    segments, language = _engine(_json_handler(body)).transcribe(wav)

    assert language == "de"
    assert segments[0].language == "de"


def test_missing_logprob_is_none(wav: Path) -> None:
    body = {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "x"}]}

    segments, _ = _engine(_json_handler(body)).transcribe(wav)

    assert segments[0].asr_logprob is None


def test_whitespace_only_segment_dropped(wav: Path) -> None:
    body = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "  \n"},
            {"start": 1.0, "end": 2.0, "text": "kept"},
        ],
    }

    segments, _ = _engine(_json_handler(body)).transcribe(wav)

    assert [s.text for s in segments] == ["kept"]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "hello"},
        {"segments": [{"text": "x"}]},
        {"segments": [{"start": None, "end": 1.0, "text": "x"}]},
        {"segments": [{"start": "a", "end": 1.0, "text": "x"}]},
        {"segments": [{"start": True, "end": 1.0, "text": "x"}]},
        {"segments": "nope"},
        {"segments": ["nope"]},
    ],
)
def test_no_timestamps_raises_naming_model(wav: Path, body: dict[str, object]) -> None:
    with pytest.raises(PanoScribeError, match="whisper-1"):
        _engine(_json_handler(body)).transcribe(wav)


def test_empty_segments_and_text_is_silence(wav: Path) -> None:
    result = _engine(_json_handler({"segments": [], "text": ""})).transcribe(wav)

    assert result == ([], "en")


def test_empty_segments_with_text_raises(wav: Path) -> None:
    with pytest.raises(PanoScribeError, match="whisper-1"):
        _engine(_json_handler({"segments": [], "text": "hi"})).transcribe(wav)


@pytest.mark.parametrize("content", [b"<html>SENTINEL", b'["SENTINEL"]'])
def test_non_json_body_raises_without_echoing(wav: Path, content: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    with pytest.raises(PanoScribeError) as info:
        _engine(handler).transcribe(wav)

    assert "SENTINEL" not in str(info.value)


def test_header_only_wav_sends_nothing(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    empty = _write_wav(tmp_path / "empty.wav", 0)

    result = _engine(_json_handler({"segments": []}, calls)).transcribe(empty)

    assert result == ([], "en")
    assert calls == []


def test_header_only_wav_falls_back_to_forced_language(tmp_path: Path) -> None:
    empty = _write_wav(tmp_path / "empty.wav", 0)

    _, language = _engine(_ok, _cfg(whisper_language="fr")).transcribe(empty)

    assert language == "fr"


def test_chunks_offset_in_order_and_first_speech_sets_language(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "audio.wav", 40.0)
    responses = iter(
        [
            {"language": "fr", "segments": [], "text": ""},
            {"language": "de", "segments": [{"start": 1.0, "end": 2.0, "text": "hallo"}]},
        ]
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=next(responses))

    segments, language = _engine(handler, _cfg(asr_remote_max_upload_mb=0.7)).transcribe(src)

    assert len(calls) == 2
    assert language == "de"
    chunk_dir = tmp_path / "remote_asr_chunks"
    with wave.open(str(chunk_dir / "chunk-0000.wav"), "rb") as first:
        first_len = first.getnframes() / RATE
    assert len(segments) == 1
    assert segments[0].start == pytest.approx(first_len + 1.0)
    assert segments[0].end == pytest.approx(first_len + 2.0)
    assert segments[0].language == "de"


def test_whole_request_body_stays_inside_the_limit(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "audio.wav", 40.0)
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.content))
        return httpx.Response(200, json={"segments": []})

    _engine(handler, _cfg(asr_remote_max_upload_mb=1.0)).transcribe(src)

    assert len(sizes) == 2
    assert max(sizes) <= 1_000_000


def test_chunk_limit_holds_back_room_for_multipart_framing(
    wav: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, Path]] = []
    real_split = remote.split_wav

    def spy(audio_path: Path, *, max_bytes: int, out_dir: Path) -> list[remote.AudioChunk]:
        seen.append((max_bytes, out_dir))
        return real_split(audio_path, max_bytes=max_bytes, out_dir=out_dir)

    monkeypatch.setattr(remote, "split_wav", spy)

    _engine(_json_handler({"segments": []}), _cfg(asr_remote_max_upload_mb=1.0)).transcribe(wav)

    assert seen == [(1_000_000 - 4096, wav.parent / "remote_asr_chunks")]


def test_limit_too_small_for_the_overhead_raises_naming_the_setting(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "audio.wav", 3.0)
    calls: list[httpx.Request] = []

    with pytest.raises(PanoScribeError, match="PANO_ASR_REMOTE_MAX_UPLOAD_MB"):
        _engine(
            _json_handler({"segments": []}, calls), _cfg(asr_remote_max_upload_mb=0.001)
        ).transcribe(src)

    assert calls == []


@pytest.mark.parametrize(
    ("raw", "want"),
    [("en", "en"), ("EN", "en"), ("english", "en"), ("German", "de"), ("zh-CN", "zh")],
)
def test_normalise_language(raw: str, want: str) -> None:
    assert _normalise_language(raw, None) == want


def test_unknown_language_warns_and_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="panoscribe.asr.remote"):
        assert _normalise_language("klingon", "fr") == "fr"
    assert "unrecognised language" in caplog.text
    assert _normalise_language(None, None) == "en"


def test_three_letter_code_passes_through() -> None:
    assert _normalise_language("haw", None) == "haw"


def test_translate_refused_before_any_request() -> None:
    with pytest.raises(PanoScribeError, match="translate"):
        RemoteTranscriber(_cfg(whisper_task="translate"))


@pytest.mark.parametrize(
    ("field", "env"),
    [
        ("asr_remote_base_url", "PANO_ASR_REMOTE_BASE_URL"),
        ("asr_remote_model", "PANO_ASR_REMOTE_MODEL"),
    ],
)
def test_missing_required_setting_names_env_var(field: str, env: str) -> None:
    with pytest.raises(PanoScribeError, match=env):
        RemoteTranscriber(_cfg(**{field: None}))


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@h/v1",
        "https://h/v1?token=abc",
        "https://h/v1#abc",
        "https://h/v1?",
        "ftp://h/v1",
        "nonsense",
        "http://",
        "https://h:badport/v1",
        "https://h /v1",
    ],
)
def test_bad_base_url_refused_without_echo(url: str) -> None:
    with pytest.raises(PanoScribeError) as info:
        RemoteTranscriber(_cfg(asr_remote_base_url=url))

    message = str(info.value)
    assert "PANO_ASR_REMOTE_BASE_URL" in message
    for secret in ("pw", "abc", "badport", url):
        assert secret not in message


@pytest.mark.parametrize("key", ["sk bad key", "sk-éclair", "sk-tab\tbad"])
def test_key_with_inner_whitespace_or_non_ascii_refused_without_echo(key: str) -> None:
    with pytest.raises(PanoScribeError) as info:
        RemoteTranscriber(_cfg(asr_remote_api_key=key))

    message = str(info.value)
    assert "PANO_ASR_REMOTE_API_KEY" in message
    assert "bad" not in message
    assert "clair" not in message


def test_missing_httpx_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)

    with pytest.raises(PanoScribeError, match="uv sync --extra remote-asr") as info:
        RemoteTranscriber(_cfg())

    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_notice_once_per_host_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="panoscribe.asr.remote"):
        RemoteTranscriber(_cfg())
        RemoteTranscriber(_cfg())

    notices = [r for r in caplog.records if "audio is being sent" in r.getMessage()]
    assert len(notices) == 1
    assert notices[0].levelno == logging.WARNING
    message = notices[0].getMessage()
    assert "asr.example.test" in message
    assert "/v1" not in message
    assert KEY not in caplog.text
    assert "unencrypted" not in message


def test_plain_http_remote_host_warns_unencrypted(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="panoscribe.asr.remote"):
        RemoteTranscriber(_cfg(asr_remote_base_url="http://asr.example.test:8000/v1"))

    assert "unencrypted" in caplog.text


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_plain_http_loopback_has_no_unencrypted_warning(
    caplog: pytest.LogCaptureFixture, host: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="panoscribe.asr.remote"):
        RemoteTranscriber(_cfg(asr_remote_base_url=f"http://{host}:8000/v1"))

    assert "audio is being sent" in caplog.text
    assert "unencrypted" not in caplog.text


def test_key_absent_from_logs_and_errors(wav: Path, caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"echo {request.headers['Authorization']}")

    with caplog.at_level(logging.DEBUG), pytest.raises(PanoScribeError) as info:
        _engine(handler).transcribe(wav)

    assert KEY not in caplog.text
    assert KEY not in str(info.value)
    assert KEY not in repr(info.value)


def test_transport_error_text_never_used(wav: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {KEY}'")

    with pytest.raises(PanoScribeError) as info:
        _engine(handler).transcribe(wav)

    assert KEY not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


# ── Retries and error mapping ────────────────────────────────────


class _Server:
    """Scripted responses; records requests and the delays the engine slept."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses[min(len(self.requests), len(self._responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    def engine(self, cfg: PanoScribeConfig | None = None) -> RemoteTranscriber:
        return RemoteTranscriber(
            cfg or _cfg(), transport=httpx.MockTransport(self.handler), sleep=self.sleeps.append
        )


_GOOD = {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}


def _good() -> httpx.Response:
    return httpx.Response(200, json=_GOOD)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_then_success(wav: Path, status: int) -> None:
    server = _Server(httpx.Response(status), _good())

    segments, _ = server.engine().transcribe(wav)

    assert [s.text for s in segments] == ["hi"]
    assert len(server.requests) == 2
    assert len(server.sleeps) == 1


def test_gives_up_after_max_retries(wav: Path) -> None:
    server = _Server(httpx.Response(503, text="BODYSENTINEL"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 4
    message = str(info.value)
    assert "503" in message
    assert "asr.example.test" in message
    assert "BODYSENTINEL" not in message


def test_zero_retries_means_one_call(wav: Path) -> None:
    server = _Server(httpx.Response(503))

    with pytest.raises(PanoScribeError):
        server.engine(_cfg(asr_remote_max_retries=0)).transcribe(wav)

    assert len(server.requests) == 1
    assert server.sleeps == []


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: httpx.ConnectError("boom"),
        lambda: httpx.ReadTimeout("slow"),
    ],
)
def test_transport_errors_retried(wav: Path, make_exc: Callable[[], Exception]) -> None:
    server = _Server(make_exc(), _good())

    segments, _ = server.engine().transcribe(wav)

    assert len(segments) == 1
    assert len(server.requests) == 2


def test_exhausted_transport_errors_name_the_exception_type_only(wav: Path) -> None:
    server = _Server(httpx.ConnectError("TEXTSENTINEL"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 4
    assert "ConnectError" in str(info.value)
    assert "TEXTSENTINEL" not in str(info.value)


def _normalised_body(request: httpx.Request) -> bytes:
    content_type = request.headers["Content-Type"]
    boundary = content_type.split("boundary=", 1)[1].encode()
    return request.content.replace(boundary, b"BOUNDARY")


def test_retry_resends_whole_audio(wav: Path) -> None:
    server = _Server(httpx.Response(503), _good())

    server.engine().transcribe(wav)

    first, second = server.requests
    assert wav.read_bytes() in first.content
    assert wav.read_bytes() in second.content
    # httpx draws a fresh multipart boundary per request; nothing else may differ.
    assert _normalised_body(first) == _normalised_body(second)


@pytest.mark.parametrize(("header", "want"), [("7", 7.0), ("3600", 60.0)])
def test_retry_after_honoured_and_capped(wav: Path, header: str, want: float) -> None:
    server = _Server(httpx.Response(429, headers={"Retry-After": header}), _good())

    server.engine().transcribe(wav)

    assert server.sleeps == [want]


@pytest.mark.parametrize("header", ["Wed, 21 Oct 2026 07:28:00 GMT", "-5", "nan", "soon"])
def test_retry_after_not_a_number_falls_back_to_backoff(wav: Path, header: str) -> None:
    server = _Server(httpx.Response(503, headers={"Retry-After": header}), _good())

    server.engine().transcribe(wav)

    (delay,) = server.sleeps
    assert 1.0 <= delay <= 2.0


def test_backoff_grows_and_is_capped(wav: Path) -> None:
    server = _Server(httpx.Response(503))

    with pytest.raises(PanoScribeError):
        server.engine(_cfg(asr_remote_max_retries=8)).transcribe(wav)

    assert len(server.sleeps) == 8
    assert max(server.sleeps) <= 60.0
    assert min(server.sleeps) >= 1.0
    assert server.sleeps[-1] > server.sleeps[0]
    assert server.sleeps[-1] >= 32.0


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_names_key_var_no_retry(wav: Path, status: int) -> None:
    server = _Server(httpx.Response(status))

    with pytest.raises(PanoScribeError, match="PANO_ASR_REMOTE_API_KEY"):
        server.engine().transcribe(wav)

    assert len(server.requests) == 1


def test_413_suggests_lower_limit_no_retry(wav: Path) -> None:
    server = _Server(httpx.Response(413))

    with pytest.raises(PanoScribeError, match="PANO_ASR_REMOTE_MAX_UPLOAD_MB"):
        server.engine().transcribe(wav)

    assert len(server.requests) == 1


def test_400_hints_model_kind_no_retry(wav: Path) -> None:
    server = _Server(httpx.Response(400, text="BODYSENTINEL"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 1
    message = str(info.value)
    assert "verbose_json" in message
    assert "whisper-1" in message
    assert "BODYSENTINEL" not in message


def test_redirect_not_followed_no_retry(wav: Path) -> None:
    server = _Server(httpx.Response(307, headers={"Location": "https://elsewhere.example/v1"}))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 1
    assert "307" in str(info.value)
    assert "base URL" in str(info.value)
    assert "elsewhere" not in str(info.value)


@pytest.mark.parametrize("status", [404, 501])
def test_other_status_no_retry(wav: Path, status: int) -> None:
    server = _Server(httpx.Response(status))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 1
    assert str(status) in str(info.value)
    assert "whisper-1" in str(info.value)


def test_error_never_carries_url_query_or_key(wav: Path) -> None:
    server = _Server(httpx.Response(503))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert KEY not in str(info.value)
    assert "/audio/transcriptions" not in str(info.value)


def test_non_transport_httpx_error_is_not_retried(wav: Path) -> None:
    server = _Server(httpx.DecodingError("TEXTSENTINEL"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 1
    assert "DecodingError" in str(info.value)
    assert "TEXTSENTINEL" not in str(info.value)


def test_failed_chunk_fails_the_run(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "audio.wav", 40.0)
    server = _Server(_good(), httpx.Response(400))

    with pytest.raises(PanoScribeError):
        server.engine(_cfg(asr_remote_max_upload_mb=0.7)).transcribe(src)

    assert len(server.requests) == 2


# ── No context left behind, hostile failures, environment ────────


def _assert_no_chain(exc: BaseException) -> None:
    """Neither ``__cause__`` nor ``__context__``: both can hold the request or the body."""
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_non_transport_httpx_error_leaves_no_chain(wav: Path) -> None:
    server = _Server(httpx.DecodingError(f"Bearer {KEY}"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    _assert_no_chain(info.value)


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: RuntimeError(f"Bearer {KEY}"),
        lambda: OverflowError("timestamp too large for a socket"),
        lambda: httpx.InvalidURL(f"bad {KEY}"),
    ],
)
def test_any_other_exception_from_post_fails_at_once_with_the_type_only(
    wav: Path, make_exc: Callable[[], Exception]
) -> None:
    exc = make_exc()
    server = _Server(exc)

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    assert len(server.requests) == 1
    assert type(exc).__name__ in str(info.value)
    assert KEY not in str(info.value)
    _assert_no_chain(info.value)


@pytest.mark.parametrize("url", ["https://☃.example/v1", "https://h.example/" + "a" * 70_000])
def test_unusable_base_url_is_a_clear_failure_without_chain(wav: Path, url: str) -> None:
    server = _Server(httpx.Response(200, json={"segments": []}))

    with pytest.raises(PanoScribeError) as info:
        server.engine(_cfg(asr_remote_base_url=url)).transcribe(wav)

    assert len(server.requests) <= 1
    _assert_no_chain(info.value)


def test_transport_failure_after_retries_leaves_no_chain(wav: Path) -> None:
    server = _Server(httpx.ConnectError(f"Bearer {KEY}"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    _assert_no_chain(info.value)


@pytest.mark.parametrize("content", [b"<html>SENTINEL", b"[" * 200_000])
def test_unparseable_reply_leaves_no_chain(wav: Path, content: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    with pytest.raises(PanoScribeError, match="not valid JSON") as info:
        _engine(handler).transcribe(wav)

    assert "SENTINEL" not in str(info.value)
    _assert_no_chain(info.value)


@pytest.mark.parametrize("url", ["https://user:sk-secret/v1", "http://host:notaport/v1"])
def test_malformed_port_in_base_url_leaves_no_chain_and_no_secret(url: str) -> None:
    with pytest.raises(PanoScribeError) as info:
        _engine(_ok, _cfg(asr_remote_base_url=url))

    assert "sk-secret" not in str(info.value)
    _assert_no_chain(info.value)


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: ImportError("sk-secret"),
        lambda: ValueError("sk-secret"),
        lambda: FileNotFoundError("sk-secret"),
    ],
)
def test_client_construction_failure_is_a_clear_failure_without_chain(
    wav: Path, monkeypatch: pytest.MonkeyPatch, make_exc: Callable[[], Exception]
) -> None:
    exc = make_exc()

    def broken_client(*args: object, **kwargs: object) -> httpx.Client:
        raise exc

    monkeypatch.setattr(httpx, "Client", broken_client)

    with pytest.raises(PanoScribeError) as info:
        _engine(_ok).transcribe(wav)

    message = str(info.value)
    assert type(exc).__name__ in message
    assert "sk-secret" not in message
    # The client never receives the base URL, so it is not the suspect.
    assert "BASE_URL" not in message
    for setting in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE"):
        assert setting in message
    _assert_no_chain(info.value)


def test_invalid_url_from_post_fails_at_once_and_points_at_the_base_url(wav: Path) -> None:
    server = _Server(httpx.InvalidURL("https://user:sk-secret@host/v1"))

    with pytest.raises(PanoScribeError) as info:
        server.engine().transcribe(wav)

    message = str(info.value)
    assert len(server.requests) == 1
    assert "InvalidURL" in message
    assert "PANO_ASR_REMOTE_BASE_URL" in message
    assert "sk-secret" not in message
    _assert_no_chain(info.value)


def test_keyboard_interrupt_from_post_passes_through_unconverted(wav: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _engine(handler).transcribe(wav)


def test_retry_after_of_an_earlier_attempt_does_not_carry_over(wav: Path) -> None:
    server = _Server(
        httpx.Response(503, headers={"Retry-After": "7"}),
        httpx.ConnectError("boom"),
        _good(),
    )

    server.engine().transcribe(wav)

    assert server.sleeps[0] == 7.0
    assert 2.0 <= server.sleeps[1] <= 4.0  # backoff for the second retry, not the stale 7


def test_retry_delay_does_not_overflow_at_a_huge_attempt_number() -> None:
    assert remote._retry_delay(2000, None) <= 60.0


def test_segment_time_beyond_the_limit_is_not_a_usable_time(wav: Path) -> None:
    content = b'{"segments": [{"start": 1e306, "end": 1e306, "text": "x"}]}'

    with pytest.raises(PanoScribeError, match="no segment timestamps"):
        _engine(_raw_handler(content)).transcribe(wav)


def test_timeout_setting_reaches_the_request(wav: Path) -> None:
    seen: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.extensions["timeout"]))
        return httpx.Response(200, json={"segments": []})

    _engine(handler, _cfg(asr_remote_timeout_s=123.0)).transcribe(wav)

    assert seen == [{"connect": 10.0, "read": 123.0, "write": 123.0, "pool": 123.0}]


# ── Segment validation, numbers, language ────────────────────────


def _raw_handler(content: bytes) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    return handler


@pytest.mark.parametrize(
    "segment",
    [
        {"start": -0.5, "end": 1.0, "text": "x"},
        {"start": 2.0, "end": 1.0, "text": "x"},
        {"start": 0.0, "end": 1.0},
        {"start": 0.0, "end": 1.0, "text": None},
        {"start": 0.0, "end": 1.0, "text": 123},
        {"start": 0.0, "end": 1.0, "text": ["x"]},
    ],
)
def test_malformed_segment_fails_the_run_and_is_not_repaired(
    wav: Path, segment: dict[str, object]
) -> None:
    body = {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "ok"}, segment]}

    with pytest.raises(PanoScribeError, match="malformed segments") as info:
        _engine(_json_handler(body)).transcribe(wav)

    assert "whisper-1" in str(info.value)
    assert "no segment timestamps" not in str(info.value)


def test_zero_length_segment_is_allowed(wav: Path) -> None:
    body = {"language": "en", "segments": [{"start": 1.0, "end": 1.0, "text": "x"}]}

    segments, _ = _engine(_json_handler(body)).transcribe(wav)

    assert [(s.start, s.end) for s in segments] == [(1.0, 1.0)]


@pytest.mark.parametrize(
    "body",
    [
        {"segments": []},
        {"segments": [], "text": None},
        {"segments": [], "text": ""},
        {"segments": [], "text": "  \n"},
    ],
)
def test_empty_segments_with_blank_or_missing_text_is_silence(
    wav: Path, body: dict[str, object]
) -> None:
    assert _engine(_json_handler(body)).transcribe(wav) == ([], "en")


@pytest.mark.parametrize("text", [123, 1.5, True, ["hi"], {"a": 1}])
def test_empty_segments_with_non_string_text_is_malformed(wav: Path, text: object) -> None:
    with pytest.raises(PanoScribeError, match="malformed segments"):
        _engine(_json_handler({"segments": [], "text": text})).transcribe(wav)


def test_huge_integer_time_is_not_a_time(wav: Path) -> None:
    content = b'{"segments": [{"start": 1' + b"0" * 400 + b', "end": 2, "text": "x"}]}'

    with pytest.raises(PanoScribeError, match="whisper-1") as info:
        _engine(_raw_handler(content)).transcribe(wav)

    assert not isinstance(info.value.__context__, OverflowError)


@pytest.mark.parametrize(
    "literal", [b"NaN", b"Infinity", b"-Infinity", b"1e999", b"1" + b"0" * 400, b'"abc"', b"true"]
)
def test_unusable_logprob_becomes_none(wav: Path, literal: bytes) -> None:
    content = (
        b'{"language": "en", "segments": [{"start": 0, "end": 1, "text": "x", "avg_logprob": '
        + literal
        + b"}]}"
    )

    segments, _ = _engine(_raw_handler(content)).transcribe(wav)

    assert [s.text for s in segments] == ["x"]
    assert segments[0].asr_logprob is None


@pytest.mark.parametrize("value", [123, ["en"], True, {"a": 1}])
def test_non_text_language_warns_and_falls_back(
    wav: Path, caplog: pytest.LogCaptureFixture, value: object
) -> None:
    body = {"language": value, "segments": [{"start": 0, "end": 1, "text": "x"}]}

    with caplog.at_level(logging.WARNING, logger="panoscribe.asr.remote"):
        _, language = _engine(_json_handler(body), _cfg(whisper_language="fr")).transcribe(wav)

    assert language == "fr"
    assert "unrecognised language" in caplog.text


def test_missing_language_stays_silent(wav: Path, caplog: pytest.LogCaptureFixture) -> None:
    body = {"segments": [{"start": 0, "end": 1, "text": "x"}]}

    with caplog.at_level(logging.WARNING, logger="panoscribe.asr.remote"):
        _, language = _engine(_json_handler(body), _cfg(whisper_language="fr")).transcribe(wav)

    assert language == "fr"
    assert "unrecognised language" not in caplog.text


def test_configured_language_used_when_no_chunk_reports_one(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "audio.wav", 40.0)
    silent = {"language": "de", "segments": [], "text": ""}

    segments, language = _engine(
        _json_handler(silent), _cfg(whisper_language="fr", asr_remote_max_upload_mb=0.7)
    ).transcribe(src)

    assert (segments, language) == ([], "fr")


@pytest.mark.parametrize(
    ("url", "trust_env"),
    [
        ("http://127.0.0.1:8000/v1", False),
        ("http://localhost:8000/v1", False),
        ("http://[::1]:8000/v1", False),
        ("https://asr.example.test/v1", True),
        ("http://10.0.0.5:8000/v1", True),
    ],
)
def test_environment_proxies_ignored_only_for_a_loopback_server(
    wav: Path, monkeypatch: pytest.MonkeyPatch, url: str, trust_env: bool
) -> None:
    seen: list[dict[str, object]] = []
    real_client = httpx.Client

    def spy(*args: object, **kwargs: object) -> httpx.Client:
        seen.append(dict(kwargs))
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "Client", spy)

    _engine(_json_handler({"segments": []}), _cfg(asr_remote_base_url=url)).transcribe(wav)

    assert [kw["trust_env"] for kw in seen] == [trust_env]


def test_building_the_engine_quiets_the_httpx_logger() -> None:
    httpx_logger = logging.getLogger("httpx")
    original = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)
    try:
        assert httpx_logger.isEnabledFor(logging.INFO)

        _engine(_ok)

        assert not httpx_logger.isEnabledFor(logging.INFO)
        assert httpx_logger.isEnabledFor(logging.WARNING)
    finally:
        httpx_logger.setLevel(original)
