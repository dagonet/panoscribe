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

    with pytest.raises(PanoScribeError, match="uv sync --extra remote-asr"):
        RemoteTranscriber(_cfg())


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
    assert info.value.__suppress_context__ is True


def test_redirects_are_not_followed(wav: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://elsewhere.example/v1"})

    with pytest.raises(PanoScribeError):
        _engine(handler).transcribe(wav)

    assert len(calls) == 1
