# Remote speech-to-text backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `AsrEngine` that sends audio to a generic OpenAI-compatible endpoint, and reword the README's "Fully local" claim in the same PR (#83, #85).

**Architecture:** `RemoteTranscriber` in `asr/remote.py` satisfies the existing `AsrEngine` protocol using plain `httpx`. `asr/wav_split.py` splits audio over the upload limit using only the standard library. `pipeline._build_asr_engine` chooses the backend at both construction sites.

**Tech Stack:** Python 3.11+, `httpx`, `pydantic-settings`, stdlib `wave`, pytest with `httpx.MockTransport`.

**Spec:** `docs/plans/remote-asr-backend-design.md`

## Global Constraints

- A user who sets none of the new config sees no behaviour change. `tests/test_whisper.py` and `tests/test_asr_protocol.py` pass unchanged.
- Base install gains no new dependency. New extra: `remote-asr = ["httpx>=0.27"]`.
- No fallback in either direction between local and remote.
- The API key never appears in a log, an exception message or chain, a transcript, a temp file or an API job result.
- Timestamps are never invented.
- The module-scope `WhisperTranscriber` name stays in `panoscribe.pipeline`; `tests/test_cli.py:116` patches it. Imports there stay at module scope, except the remote module, which is imported only when selected.
- `asr/` modules import nothing from other subsystems (`docs/architecture.md`, Layering rules). `panoscribe.errors`, `panoscribe.output` and `panoscribe.config` are allowed.
- Gate: `cct-gate <absolute worktree path>`. It requires 95% coverage, and the commit hook runs it, so each task commits its tests with its code.
- Commit rules: `git add` in its own call, before `git commit -F <message file>`.

## Review Focus

- A key pasted with a trailing newline, or an `httpx` error that quotes a header: the key is stripped or refused, and never appears in any message or exception chain. (Task 1, Task 3, Task 4)
- A base URL holding credentials or a query string: refused without echoing it, and not via pydantic, whose errors print the input. (Task 3)
- A retry after a 503: the second attempt carries the whole audio again, not an exhausted stream. (Task 4)
- Audio a few frames over the limit: no tiny trailing chunk that a server would refuse as too short. (Task 2)
- A silent intro or a header-only WAV: no upload for an empty file, no invented segments, and the language comes from the first chunk with speech. (Task 2, Task 3)

---

### Task 1: Config fields and the extra

**Files:**
- Modify: `src/panoscribe/config.py`, `pyproject.toml`, `uv.lock`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `PanoScribeConfig` fields `asr_backend: Literal["local", "remote"] = "local"`, `asr_remote_base_url: str | None = None`, `asr_remote_model: str | None = None`, `asr_remote_api_key: SecretStr | None = None`, `asr_remote_timeout_s: float = 600.0`, `asr_remote_max_retries: int = 3`, `asr_remote_max_upload_mb: float = 25.0`.

- [ ] **Step 1: Write the failing tests**

```python
def test_remote_asr_defaults(monkeypatch):
    # clear PANO_ env the same way test_defaults does
    cfg = PanoScribeConfig(_env_file=None)
    assert cfg.asr_backend == "local"
    assert cfg.asr_remote_base_url is None
    assert cfg.asr_remote_model is None
    assert cfg.asr_remote_api_key is None
    assert cfg.asr_remote_timeout_s == 600.0
    assert cfg.asr_remote_max_retries == 3
    assert cfg.asr_remote_max_upload_mb == 25.0

def test_remote_asr_unknown_backend_rejected(): ...       # asr_backend="cloud" -> ValidationError

@pytest.mark.parametrize("field,value", [
    ("asr_remote_timeout_s", 0.0), ("asr_remote_timeout_s", -1.0),
    ("asr_remote_max_retries", -1),
    ("asr_remote_max_upload_mb", 0.0), ("asr_remote_max_upload_mb", -1.0),
])
def test_remote_asr_numeric_validation(field, value): ... # ValidationError

def test_remote_asr_blank_values_become_none(monkeypatch):
    # PANO_ASR_REMOTE_BASE_URL, _MODEL and _API_KEY set to "" -> all None

def test_remote_asr_key_is_stripped_and_masked(monkeypatch):
    monkeypatch.setenv("PANO_ASR_REMOTE_API_KEY", " sk-test-secret\n")
    cfg = PanoScribeConfig(_env_file=None)
    assert cfg.asr_remote_api_key.get_secret_value() == "sk-test-secret"
    assert "sk-test-secret" not in repr(cfg)

def test_remote_asr_whitespace_only_key_becomes_none(monkeypatch):
    monkeypatch.setenv("PANO_ASR_REMOTE_API_KEY", "  \n")
    assert PanoScribeConfig(_env_file=None).asr_remote_api_key is None
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/test_config.py -k remote_asr -v`. Expected: FAIL.

- [ ] **Step 3: Add the fields and validators**

Add a `# ── Remote ASR` block after the ASR fields. Add the three optional fields to `_empty_to_none`. Add a `mode="before"` validator that strips whitespace from `asr_remote_api_key` and `asr_remote_base_url`. Add `mode="after"` validators for the numeric rules, in the style of `_validate_llm_cleanup_timeout_s`. **Do not validate the URL or key content here:** pydantic's `ValidationError` prints the input. Task 3 does that.

- [ ] **Step 4: Add the extra.** Add `remote-asr = ["httpx>=0.27"]` to `[project.optional-dependencies]`. Run `uv lock`. Add a commented-out block for the seven variables to `.env.example`.

- [ ] **Step 5: Run to verify they pass.** Run: `uv run pytest tests/test_config.py -v`. Expected: PASS.

- [ ] **Step 6: Commit** as `feat: add remote ASR configuration (#83)`.

---

### Task 2: WAV splitter

**Files:**
- Create: `src/panoscribe/asr/wav_split.py`
- Test: `tests/test_wav_split.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class AudioChunk` with `path: Path` and `start_s: float`; `split_wav(audio_path: Path, *, max_bytes: int, out_dir: Path) -> list[AudioChunk]`.

- [ ] **Step 1: Write the failing tests**

Helper: `_wav(path, segments)` writes 16 kHz mono 16-bit PCM from `(seconds, amplitude)` pairs. `MAX = 44 + 18 * 32000` is 18 s of audio.

```python
def test_within_limit_returns_original_and_writes_nothing(tmp_path):
    src = _wav(tmp_path / "a.wav", [(5, 9000)]); out = tmp_path / "chunks"
    assert split_wav(src, max_bytes=MAX, out_dir=out) == [AudioChunk(src, 0.0)]
    assert not out.exists()

def test_header_only_wav_returns_empty(tmp_path): ...     # zero frames -> []

def test_cuts_inside_quiet_gap(tmp_path):
    src = _wav(tmp_path / "a.wav", [(15, 9000), (1, 0), (15, 9000)])
    chunks = split_wav(src, max_bytes=MAX, out_dir=tmp_path / "c")
    assert 15.0 <= chunks[1].start_s <= 16.0

def test_chunks_fit_limit_and_preserve_every_frame(tmp_path):
    # 60 s uniform tone: every file size <= MAX, the concatenated frames equal the
    # source frames exactly, and each start_s equals the sum of earlier durations

def test_just_over_limit_leaves_no_tiny_tail(tmp_path):
    # 18.2 s uniform tone: exactly 2 chunks, last one >= 1.0 s

def test_uniform_audio_cuts_at_latest_window(tmp_path):
    # tie on energy: first chunk ends within the last 100 ms of the allowed range

def test_limit_below_one_second_raises(tmp_path):         # max_bytes=1000
    # PanoScribeError matching "PANO_ASR_REMOTE_MAX_UPLOAD_MB"

@pytest.mark.parametrize("bad", ["8-bit wav", "not a wav"])
def test_unsupported_input_raises(tmp_path, bad):         # PanoScribeError
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/test_wav_split.py -v`. Expected: FAIL with an import error.

- [ ] **Step 3: Implement `split_wav`**

Constants: `_SEARCH_S = 10.0`, `_WINDOW_S = 0.1`, `_MIN_CHUNK_S = 1.0`, `_WAV_HEADER_BYTES = 44`. Read through `wave` so memory stays near one chunk, not the whole file. Convert `wave.Error` and `EOFError` to `PanoScribeError`, and require sample width 2.

```
max_frames = (max_bytes - header) // frame_size   # under min_frames -> PanoScribeError
pos = 0
while total - pos > max_frames:
    latest = min(pos + max_frames, total - min_frames)
    earliest = max(pos + min_frames, latest - search_frames)
    cut = midpoint of the lowest-energy window in [earliest, latest], ties to the
          latest window; `latest` itself if the range is narrower than one window
    write [pos, cut) to out_dir / f"chunk-{n:04d}.wav"; pos = cut
write [pos, total)
```

Check zero frames first, then file size within `max_bytes`, and only then create `out_dir`.

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest tests/test_wav_split.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** as `feat: split long WAV audio at quiet points (#83)`.

---

### Task 3: RemoteTranscriber, one request per chunk

**Files:**
- Create: `src/panoscribe/asr/remote.py`
- Test: `tests/test_remote_asr.py`

**Interfaces:**
- Consumes: the Task 1 fields, `split_wav` and `AudioChunk`.
- Produces: `RemoteTranscriber(config: PanoScribeConfig, *, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep)` with `transcribe(audio_path: Path) -> tuple[list[TranscriptSegment], str]`; `_normalise_language(value: object, fallback: str | None) -> str`; module-level `_announced_hosts: set[str]`; `_post_chunk(self, client: httpx.Client, chunk: AudioChunk) -> dict[str, object]`, which Task 4 extends.

- [ ] **Step 1: Write the failing tests**

Helpers: `_cfg(**over)` builds a remote config with `https://asr.example.test/v1`, `whisper-1` and `sk-test-secret`; `_engine(handler, cfg=None)` injects `httpx.MockTransport(handler)` and a no-op sleep. An autouse fixture clears `_announced_hosts`.

```python
def test_satisfies_protocol(): assert isinstance(_engine(_ok), AsrEngine)

def test_request_shape(wav):
    # url == "https://asr.example.test/v1/audio/transcriptions", multipart body has
    # model=whisper-1, response_format=verbose_json, timestamp_granularities[]=segment,
    # the WAV bytes; header Authorization == "Bearer sk-test-secret"; no language field

def test_language_sent_when_forced(wav): ...              # whisper_language="de" -> language=de
def test_no_auth_header_without_key(wav): ...
def test_trailing_slash_in_base_url_gives_single_slash(wav): ...

def test_maps_segments(wav):
    # {"language":"en","segments":[{"start":1.0,"end":2.5,"text":" hi ","avg_logprob":-0.2}]}
    # -> TranscriptSegment(start=1.0, end=2.5, text="hi", asr_logprob=-0.2, language="en"), "en"

def test_missing_logprob_is_none(wav): ...
def test_whitespace_only_segment_dropped(wav): ...

@pytest.mark.parametrize("body", [
    {"text": "hello"},                                    # no segments key
    {"segments": [{"text": "x"}]},                        # no times
    {"segments": [{"start": None, "end": 1.0, "text": "x"}]},
    {"segments": [{"start": "a", "end": 1.0, "text": "x"}]},
])
def test_no_timestamps_raises_naming_model(wav, body):    # PanoScribeError, contains "whisper-1"

def test_empty_segments_and_text_is_silence(wav):         # -> ([], "en") and no error
def test_empty_segments_with_text_raises(wav): ...        # {"segments":[],"text":"hi"}
def test_non_json_body_raises_without_echoing(wav): ...   # body b"<html>SENTINEL" -> not in message
def test_header_only_wav_sends_nothing(tmp_path): ...     # ([], "en"), handler never called

def test_chunks_offset_in_order_and_first_speech_sets_language(tmp_path):
    # 40 s WAV, asr_remote_max_upload_mb small enough for 2 chunks: first response
    # silent with language "fr", second has one segment at 1.0 with language "de"
    # -> segment.start == chunks[1].start_s + 1.0, detected language "de"

def test_whole_request_body_stays_inside_the_limit(tmp_path):
    # 40 s WAV, asr_remote_max_upload_mb=1.0: every request body, multipart framing
    # included, is at most 1_000_000 bytes

def test_limit_too_small_for_the_overhead_raises_naming_the_setting(tmp_path):
    # asr_remote_max_upload_mb=0.001: PanoScribeError matching
    # "PANO_ASR_REMOTE_MAX_UPLOAD_MB", handler never called

@pytest.mark.parametrize("raw,want", [("en","en"),("EN","en"),("english","en"),
                                       ("German","de"),("zh-CN","zh")])
def test_normalise_language(raw, want): assert _normalise_language(raw, None) == want

def test_unknown_language_warns_and_falls_back(caplog):
    assert _normalise_language("klingon", "fr") == "fr"; assert _normalise_language(None, None) == "en"

def test_translate_refused_before_any_request(): ...      # whisper_task="translate" -> error names translate
@pytest.mark.parametrize("field", ["asr_remote_base_url", "asr_remote_model"])
def test_missing_required_setting_names_env_var(field): ...

@pytest.mark.parametrize("url", ["https://user:pw@h/v1", "https://h/v1?token=abc", "ftp://h/v1", "nonsense"])
def test_bad_base_url_refused_without_echo(url): ...      # "pw" and "abc" are not in the message

def test_key_with_inner_whitespace_refused_without_echo(): ...
def test_missing_httpx_gives_install_hint(monkeypatch):   # sys.modules["httpx"] = None -> "uv sync --extra remote-asr"

def test_notice_once_per_host_at_warning(caplog):         # two engines -> one WARNING naming only the host
def test_plain_http_remote_host_warns_unencrypted(caplog): ...
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_plain_http_loopback_has_no_unencrypted_warning(caplog, host): ...

def test_key_absent_from_logs_and_errors(wav, caplog):
    # a failing response: "sk-test-secret" not in caplog.text, str(exc) or repr(exc)
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/test_remote_asr.py -v`. Expected: FAIL with an import error.

- [ ] **Step 3: Implement the constructor**

In this order: refuse translate, require URL and model, check URL and key content, import `httpx` lazily and store it on `self`, then announce. Message for missing `httpx`: names `uv sync --extra remote-asr`. A URL needs an `http` or `https` scheme, a host, no user-info, no query and no fragment. A key must contain only printable ASCII with no whitespace. Loopback means `localhost`, or an address for which `ipaddress` reports `is_loopback`.

- [ ] **Step 4: Implement `transcribe` and `_post_chunk`**

`max_bytes = int(asr_remote_max_upload_mb * 1_000_000) - _REQUEST_OVERHEAD_BYTES`, with `_REQUEST_OVERHEAD_BYTES = 4096`, so a chunk plus the multipart framing around it stays inside the configured limit. Chunks go in `audio_path.parent / "remote_asr_chunks"`. One `httpx.Client(transport=..., timeout=httpx.Timeout(asr_remote_timeout_s, connect=10.0), follow_redirects=False)` per `transcribe` call. Read the file's bytes inside `_post_chunk`. In this task `_post_chunk` handles only the 2xx path and raises a generic `PanoScribeError` otherwise; Task 4 completes it. Use one language for every segment of a run: from the first chunk with segments, then `whisper_language`, then `"en"`. Provide the language table for the Whisper language set.

- [ ] **Step 5: Run to verify they pass.** Run: `uv run pytest tests/test_remote_asr.py -v`. Expected: PASS.

- [ ] **Step 6: Commit** as `feat: add remote OpenAI-compatible ASR engine (#83)`.

---

### Task 4: Retries and error mapping

**Files:**
- Modify: `src/panoscribe/asr/remote.py`
- Test: `tests/test_remote_asr.py`

**Interfaces:**
- Consumes: `_post_chunk` from Task 3 and the injected `sleep`.
- Produces: no new public names.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_then_success(wav, status): ...  # 1 failure then 200 -> ok, 2 calls

def test_gives_up_after_max_retries(wav):
    # always 503, default config -> exactly 4 calls; error contains "503" and the host

def test_zero_retries_means_one_call(wav): ...

@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_errors_retried(wav, exc): ...

def test_retry_resends_whole_audio(wav):
    # 503 then 200: the WAV bytes are in both requests' bodies, and the bodies are equal

@pytest.mark.parametrize("header,want", [("7", 7.0), ("3600", 60.0)])
def test_retry_after_honoured_and_capped(wav, header, want): ...  # sleep called with want

def test_retry_after_date_falls_back_to_backoff(wav): ... # no error; sleep within 1..2 s

def test_backoff_grows_and_is_capped(wav):
    # always 503, asr_remote_max_retries=8: delays never exceed 60.0, and later ones
    # are larger than the first

@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_names_key_var_no_retry(wav, status): ...  # 1 call, "PANO_ASR_REMOTE_API_KEY"

def test_413_suggests_lower_limit_no_retry(wav): ...      # 1 call, "PANO_ASR_REMOTE_MAX_UPLOAD_MB"
def test_400_hints_model_kind_no_retry(wav): ...          # 1 call, "verbose_json", "whisper-1"

def test_redirect_not_followed_no_retry(wav):
    # 307 with Location: 1 call only; error has "307" and "base URL"

def test_other_status_no_retry(wav): ...                  # 404 and 501: 1 call, status and model named

def test_transport_error_text_never_used(wav):
    # handler raises httpx.LocalProtocolError("Illegal header value b'Bearer sk-test-secret'")
    # -> "sk-test-secret" not in str(exc); exc.__cause__ is None; exc.__suppress_context__ is True

def test_failed_chunk_fails_the_run(tmp_path):
    # 2 chunks, second always 400 -> raises, no partial result
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/test_remote_asr.py -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement the retry loop in `_post_chunk`**

Retry on `{429, 500, 502, 503, 504}` and `httpx.TransportError`. Total attempts are `asr_remote_max_retries + 1`. Delay: a numeric `Retry-After` capped at `60.0` when present, else exponential from `1.0` s, capped at `60.0`, with jitter that keeps it within the cap and at or above the base step. Read the file bytes on each attempt, or once before the loop and reuse them, never a file handle. Errors name the host and the status or exception type, never exception text, headers or the response body, and are raised `from None`.

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest tests/test_remote_asr.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** as `feat: add retries and error mapping to remote ASR (#83)`.

---

### Task 5: Wire into the pipeline and document (#85)

**Files:**
- Modify: `src/panoscribe/pipeline.py:134,167`, `README.md`, `docs/configuration.md`, `docs/architecture.md`, `docs/troubleshooting.md`, `CHANGELOG.md`
- Test: `tests/test_asr_backend_selection.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `RemoteTranscriber` from Task 3.
- Produces: `_build_asr_engine(config: PanoScribeConfig) -> AsrEngine` in `panoscribe.pipeline`.

- [ ] **Step 1: Write the failing tests**

```python
def test_default_builds_whisper(): ...                    # patched WhisperTranscriber is called
def test_remote_builds_remote_not_whisper(): ...          # patched panoscribe.asr.remote.RemoteTranscriber called; Whisper not
def test_video_branch_uses_remote(tmp_path): ...          # process_single_video, patch set as in tests/test_cli.py:116
def test_photo_branch_uses_remote(tmp_path): ...          # directory source with images plus audio
def test_local_never_imports_remote():
    # default config: "panoscribe.asr.remote" is not added to sys.modules by
    # _build_asr_engine (drop it from sys.modules first with monkeypatch)
def test_api_job_translate_with_remote_fails_cleanly(...):
    # _run_job with translate=True and a remote config -> JobStatus.failed, error
    # mentions translate; no key in the job's error
def test_job_request_has_no_remote_asr_fields():
    assert not any(f.startswith("asr_") for f in JobRequest.model_fields)
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/test_asr_backend_selection.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `_build_asr_engine` and use it at both sites.** The remote import goes inside the function.

- [ ] **Step 4: Run to verify they pass, then the existing suites.** Run: `uv run pytest tests/test_asr_backend_selection.py tests/test_api.py tests/test_cli.py tests/test_whisper.py tests/test_asr_protocol.py -v`. Expected: PASS, with `test_whisper.py` and `test_asr_protocol.py` unedited.

- [ ] **Step 5: Write the docs**

`README.md`: replace the "Fully local" bullet with exactly this:

> - **Local by default** — The default install and config do all inference on your machine, with no API keys or cloud services. Remote speech recognition is an explicit opt-in, switched on only by settings with no defaults. When it is on, **your audio leaves the machine** and goes to the provider you configured. See [Remote speech recognition](#remote-speech-recognition-opt-in).

Add a section `## Remote speech recognition (opt-in)`: the supported install `uv sync --extra remote-asr`; the three settings that switch it on and the optional key; that the endpoint must be OpenAI-compatible and the model must return `verbose_json` with segment timestamps, such as `whisper-1`-style models, while `gpt-4o-transcribe`-style models won't work; that `--translate` is not supported; that OCR stays local, so a machine that cannot run local models also needs `--no-ocr` or `PANO_OCR_DEVICE=cpu`. Do not say the extra is what enables it.

`docs/configuration.md`: a "Remote ASR" field table and rows in "Validation rules". `docs/architecture.md`: module-map rows, an "Extension seams" row for a new ASR backend, and a short note recording "local by default, remote is opt-in". `docs/troubleshooting.md`: entries for "model returned no timestamps", the 400 rejection and "upload too large". `CHANGELOG.md`: an entry in the current style.

- [ ] **Step 6: Run the gate.** Run: `cct-gate <absolute worktree path>`. Expected: green, including the 95% coverage floor.

- [ ] **Step 7: Commit** as `feat: wire remote ASR into the pipeline and reword local claim (#83, #85)`.

- [ ] **Step 8: Open the PR.** Body: `Closes #83`, `Closes #85`, `Refs #77`. It must state that the settings are the opt-in, which departs from the wording of #83 and #85 by the user's decision, and that no real server was exercised by the automated tests. Do not close #77.
