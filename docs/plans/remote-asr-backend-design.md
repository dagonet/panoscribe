# Opt-in remote speech-to-text backend (#83, with #85)

Status: approved by the user, 2026-11-05.

## Why

Someone asked in #77 to call speech and text recognition through an API because they could not deploy models locally. The maintainer accepted that as opt-in work. Local inference stays the default and the recommended path.

Today speech recognition runs only through faster-whisper in-process. The `AsrEngine` seam it needs already exists (#82, closed). This change adds a second backend behind that seam and corrects the README's "Fully local" claim in the same PR, as #85 requires.

## Decided by the user

- Target a **generic OpenAI-compatible endpoint**, not one named vendor, so hosted services and self-hosted servers both work.
- Order: #83 and #85 together first, #84 (remote OCR) afterwards as separate work.
- **The settings are the opt-in**, not an install step. #83 and #85 both ask for "an extra and a config change", but the extra's only dependency, `httpx`, already comes with every install (`faster-whisper` -> `huggingface-hub` -> `httpx`, checked in `uv.lock`), so that step would gate nothing. The user chose this over building on the `openai` package to make the extra a real step. This departs from the wording of both issues on purpose, so the PR must say so.

## Goals

- A user can set a few `PANO_` variables and get speech segments from a remote endpoint, with the rest of the pipeline unchanged.
- A long video works, not only a short clip: audio over the upload limit is split and the timestamps stay correct.
- The README and docs say plainly that audio leaves the machine when this is on.

## Non-goals

- Remote OCR (#84). OCR stays local in this change.
- A smaller base install. `faster-whisper` stays a base dependency and `panoscribe.pipeline` keeps importing it at module scope. The remote backend avoids the model download and the GPU, not the package.
- Vendor-specific features: word-level timestamps, speaker labels, streaming, prompts.
- Remote translation (see "Translate" below).

## Anti-goals: a failure even if it works

- Audio is sent anywhere without the user having explicitly opted in, including as a fallback when local fails.
- Local processing silently replaces a failed remote call, or the reverse. A failed run fails and says why.
- The API key appears in a log, an exception message, a transcript, a temp file or the API server's job result.
- Timestamps are invented for a provider that returned none.
- Any behaviour changes for a user who has not set the new config. The existing test suites must pass unchanged.

## Configuration

New fields on `PanoScribeConfig`. All are environment or `.env` only, with no CLI flags, so a key can never land in shell history.

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `asr_backend` | `PANO_ASR_BACKEND` | `"local"` | `"local"` or `"remote"` |
| `asr_remote_base_url` | `PANO_ASR_REMOTE_BASE_URL` | none | Base including version, e.g. `https://host/v1`. Required when remote. No vendor default. |
| `asr_remote_model` | `PANO_ASR_REMOTE_MODEL` | none | Required when remote. No vendor default. |
| `asr_remote_api_key` | `PANO_ASR_REMOTE_API_KEY` | none | `SecretStr`. Optional, because self-hosted servers often need none. |
| `asr_remote_timeout_s` | `PANO_ASR_REMOTE_TIMEOUT_S` | `600.0` | Read timeout per request, must be > 0. Connect timeout is fixed at 10 s. |
| `asr_remote_max_retries` | `PANO_ASR_REMOTE_MAX_RETRIES` | `3` | Must be >= 0. |
| `asr_remote_max_upload_mb` | `PANO_ASR_REMOTE_MAX_UPLOAD_MB` | `25.0` | Upload size above which audio is split, must be > 0. 25 MB is the documented cap for this API shape: OpenAI's speech-to-text guide says "Files can be up to 25 MB" (checked 2026-11-05). Forum reports show its 413 quoting 26214400 bytes, which covers the whole request. Here 1 MB means 1,000,000 bytes and 4 KiB is held back for multipart framing, so a chunk plus its framing stays inside the limit under either reading. |

The opt-in is `PANO_ASR_BACKEND=remote` together with a base URL and a model, neither of which has a default, so it cannot switch on by accident. Nothing else can select this backend.

Existing `whisper_model`, `whisper_device`, `whisper_compute_type` and `whisper_batch_size` are ignored when remote. `whisper_language` is honoured and sent as `language`.

The API server's job request has no field that can reach the new config, and must not gain one: a client must not be able to redirect audio to another host.

## Packaging

New extra `remote-asr = ["httpx>=0.27"]`, with `uv.lock` updated. Plain `httpx`, not the `openai` package: the surface is one multipart POST, and retry behaviour stays ours. The base install gains no new dependency.

The extra declares the dependency this feature uses directly, so the feature does not lean silently on another package's dependencies. It is not what switches the feature on, and the docs must not say it is. They give `uv sync --extra remote-asr` as the supported install.

## Components

- `src/panoscribe/asr/remote.py`: `RemoteTranscriber`, satisfying `AsrEngine`. `httpx` is imported inside it lazily, with a `PanoScribeError` naming `uv sync --extra remote-asr` when missing. That path cannot fire on a normal install today; it guards against `httpx` later dropping out of the transitive chain.
- `src/panoscribe/pipeline.py`: a small `_build_asr_engine(config)` used at both construction sites (photo branch and video branch). It imports the remote module only when `asr_backend == "remote"`. The module-scope `WhisperTranscriber` name stays, because `tests/test_cli.py` patches `panoscribe.pipeline.WhisperTranscriber`.
- `src/panoscribe/config.py`: fields and validators above.

## Request and response

`POST {base_url}/audio/transcriptions`, multipart: `file`, `model`, `response_format=verbose_json`, `timestamp_granularities[]=segment`, and `language` when `whisper_language` is set. `Authorization: Bearer <key>` only when a key is set. Redirects stay off, the `httpx` default, so the key cannot follow one to another host.

Mapping each response segment to `TranscriptSegment`:

- `start`, `end`: floats, plus the chunk's offset.
- `text`: stripped.
- `asr_logprob`: `avg_logprob` when present, else `None`.
- `language`: the normalised language below.

Validity rules:

- Response has no `segments` key, or a segment lacks `start`/`end`: `PanoScribeError` saying the model returned no timestamps and is unusable, naming the configured model. This covers servers that silently ignore `verbose_json`. Models that refuse it outright arrive as a 400 instead (see the table below). OpenAI's `gpt-4o-transcribe` family supports only plain JSON per its API reference, and secondary sources report a 400 for it. The docs must describe both symptoms and name `whisper-1`-style models as the working kind.
- Empty `segments` with empty `text`: valid silence, not an error.
- Non-JSON or malformed body: `PanoScribeError` without echoing the body, which could be large or carry request details.

### Detected language

The second return value of `transcribe` drives OCR language auto-resolution (`_resolve_ocr_language`), which expects an ISO code, while `verbose_json` may return a full name such as `english`. So normalise: a two-letter code passes through lowercased, a known English language name maps to its code, and anything else logs a warning and falls back to `whisper_language`, then `"en"`. With several chunks, use the language of the first chunk that returned segments, because a silent intro tells us nothing.

Checked 2026-11-05 against OpenAI's API reference: its `verbose_json` examples show `"language": "english"`, a full lowercase name, and the schema marks `segments` as optional. The same vendor's speech-to-text guide says `timestamp_granularities[]` is supported only for `whisper-1`. Tests cover both language forms, with mocks built from that documented shape.

## Long audio

The pipeline hands over a 16 kHz mono PCM WAV (about 1.92 MB per minute), so a 25 MB cap is reached at about 13 minutes.

If the file is within `asr_remote_max_upload_mb`, upload it as is. Otherwise split it with the standard library's `wave` module, into files under the pipeline's temp dir, which it already deletes at the end of a run:

- Each chunk stays under the limit, including the WAV header.
- Cut at the quietest 100 ms window inside the last 10 s of each chunk, so words are rarely cut in half. No overlap, so no de-duplication step is needed.
- Upload chunks one at a time, in order, and add each chunk's start time to its segments.
- Any chunk failing fails the whole run. No partial transcript.

`RemoteTranscriber` derives the chunk folder from `audio_path.parent`, a subfolder, so it does not need the temp dir passed in.

## Retries, rate limits and errors

| Result | Behaviour |
|---|---|
| 429, 500, 502, 503, 504, connect error, timeout | Retry up to `asr_remote_max_retries` with exponential backoff and jitter (1 s base, 60 s cap). Honour a numeric `Retry-After`, capped at 60 s. |
| 401, 403 | No retry. `PanoScribeError` naming `PANO_ASR_REMOTE_API_KEY`. |
| 413 | No retry. Error suggesting a lower `PANO_ASR_REMOTE_MAX_UPLOAD_MB`. |
| 400 | No retry. Error with the status and model name, plus the hint that this backend needs a model returning `verbose_json` with segment timestamps, such as `whisper-1`-style models. |
| 3xx | No retry and no redirect followed. Error with the status, saying to check the base URL. |
| Any other status | No retry. Error with the status and the model name. |

Errors raised after retries name the host and the status, never the headers, key or query string. Batch mode's existing per-item error handling covers these unchanged.

## Translate

Declared **unsupported** for this backend in this change, which #83 allows. `whisper_task == "translate"` with `asr_backend == "remote"` raises a `PanoScribeError` before any upload, from the engine's constructor, so CLI, batch and API server all behave the same.

Reason: OCR auto-resolution needs the source language, translation endpoints may not report it reliably, and support varies across servers. Revisit if someone asks.

## Honesty at run time

- On engine construction, log one WARNING: audio is being sent to `<host>`, and only the host, never the full URL or key. It is a WARNING because `panoscribe batch` raises the package logger to WARNING for its whole loop (`_quiet_pipeline_logging`), so an INFO line would vanish in the mode that uploads the most audio.
- The engine is built once per video or API job, so the notice is limited to once per process per host, with a module-level set in `remote.py`. Tests reset that set.
- A `http://` base URL whose host is not loopback adds to that same notice: audio and any key travel unencrypted. It does not refuse, because self-hosted LAN servers are a real case.

## Secrets

- `SecretStr` so `repr` and `model_dump` mask it. Only `RemoteTranscriber` calls `get_secret_value`.
- Set the header on the request; never log headers. `httpx`'s own INFO logs show the URL, so the base URL must not be a place for credentials: reject a base URL containing user-info or a query string in the engine's constructor. Not in a pydantic validator, because pydantic's `ValidationError` prints the input value, which would echo what it refuses. A key containing whitespace or non-printable characters is refused in the same place, without echoing it.
- `httpx` error text can quote headers (an illegal header value appears in the `LocalProtocolError` message), so its exception text is never used and errors are raised `from None`.
- A test asserts the key appears in no captured log and no raised error message.

## Documentation (#85, same PR)

- `README.md`: replace the "Fully local" bullet with "Local by default", stating that default install and config do all inference on-device with no keys or cloud; that remote speech recognition exists as an explicit opt-in, switched on only by settings with no defaults; and that when it is on, **user audio leaves the machine** and goes to the configured provider. Add a short section with the setup.
- Include the hint that OCR stays local: a machine with no GPU and no wish to run local models also needs `--no-ocr` or `PANO_OCR_DEVICE=cpu`.
- `docs/configuration.md`: new table section.
- `docs/architecture.md`: a short note recording "local by default, remote is opt-in" as the positioning. No new ADR folder.
- `docs/troubleshooting.md`: "model returned no timestamps" and "upload too large".
- Do not close #77; the follow-up comment there is the maintainer's to send.

## Tests

All without network, using `httpx.MockTransport` or an injected client. `httpx` is already in the `dev` extra.

- `isinstance(RemoteTranscriber(cfg), AsrEngine)`.
- Default config still builds `WhisperTranscriber`; `tests/test_whisper.py` and `tests/test_asr_protocol.py` pass unchanged.
- Request shape: path, fields, header present with a key and absent without.
- Mapping, offsets across chunks, language normalisation in both forms.
- No-timestamps response, empty silence and malformed body.
- Splitting: chunks under the limit, frame count preserved in total, cut near a quiet point, on a generated WAV.
- Retry table: each row, using an injected sleep so tests do not wait. `Retry-After` honoured and capped.
- `translate` refused before any request. Missing URL or model refused with a clear message. A forced `ImportError` for `httpx` gives the install message.
- Key absent from logs and error text.

**Not covered by those tests:** a real server. The builder cannot call a paid endpoint. The tester should run once against a local OpenAI-compatible server if one can be installed on the test machine; otherwise that gap is stated in the PR, not hidden.

## Left to the builder

Helper names and module layout inside `remote.py`, the language-name table's contents (the Whisper language set), and the jitter formula.

## Size and pipeline

Roughly 250-350 lines with tests, plus docs, which is T4 by size. No architect, since this document covers that step: `cct:python-coder`, then reviewer, then tester, then the green-CI merge gate.

## Changes after code review (2026-11-06)

- Segments with `start < 0`, `end < start`, or missing or non-string `text` fail the run. They are not clamped or dropped.
- `asr_remote_timeout_s` and `asr_remote_max_upload_mb` must be finite.
- A loopback server ignores environment proxy settings, so audio for a local server cannot leave through a proxy. Other hosts honour them.
- The `httpx` logger is raised to WARNING when the remote engine is built, because a token in a URL path cannot be recognised.
- `pretty_exceptions_show_locals=False` on the CLI, because Typer's default printed the key in tracebacks on allowed versions.
- Failures are raised outside the `except` block, so `__context__` is empty as well as `__cause__`.
- Limits exist so that absurd values fail clearly: `asr_remote_max_upload_mb` is at most 1,000,000, and a segment time above 1e9 s counts as unusable.
