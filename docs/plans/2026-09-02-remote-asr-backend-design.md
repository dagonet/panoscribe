# Design — opt-in remote-API ASR backend (issue #83)

**Status: PROPOSAL, NOT APPROVED.** Written 2026-09-02 while the requester was
unavailable. Design decisions 1-4 below were made interactively with the user;
the architecture was then challenged by the `architect` agent, which found three
blocking defects. This document is the revised design incorporating those
findings. **No code has been written and none will be until this is approved.**

Spec location follows this repository's convention (`docs/plans/`, 37 dated
records) rather than the brainstorming skill's `docs/superpowers/specs/` default.

---

## 1. Motivation, and an honest caveat about it

Issue #83 traces to #77, where a user reported being unable to deploy models
locally and asked for API-based OCR/ASR.

**The motivating case is unconfirmed, and that must not be quietly forgotten.**
The reporter never replied to three requests for OS, architecture, Python
version and error text. Their failure was most likely a **PyPI name collision**:
they were told to `pip install omniscribe`, which installs an unrelated project
(SoberMind Offline Session Transcriber — also Whisper-based, which is why the
mix-up survived). Four genuine install bugs were also fixed in v0.3.0, and the
project has since been renamed `omniscribe` → `panoscribe`.

The owner's own position at the time was:

> "I have deliberately not built them yet, because if your problem was one of the
> install bugs above, an API key would have been an expensive workaround for
> something that was broken on our side."

That precondition was never resolved. The user has nonetheless chosen to build
this **on general merit** — remote ASR stands on its own for users on locked-down
machines, users who want a specific provider's accuracy, and users unwilling to
pull ~1.6 GB of weights. #77 is recorded here as *motivation*, not *validated
demand*.

**Note:** issues #83/#84/#85 are stale on two details — they reference
`env_prefix="OMNI_"` and `src/omniscribe/`. The live names are `PANO_` and
`src/panoscribe/`.

## 2. Scope

**In scope.** One additional `AsrEngine` implementation reachable only by
explicit opt-in, plus the configuration, error handling, tests and documentation
it requires.

**Out of scope.** Remote OCR (#84 — deliberately not sharing an abstraction with
this work; see §11). Speaker diarization. Chunking of unbounded-length audio.
Any change to the local backend's behaviour.

**Non-negotiable.** The default install and default configuration do all
inference on-device. Reaching this backend requires *both* an explicit config
opt-in *and* installing an extra. It is never a fallback and never implicit.

## 3. Decisions

Each was taken deliberately with the user; the rationale is recorded so a future
reader can tell a decision from an accident.

### 3.1 Generic OpenAI-compatible endpoint only

No vendor SDK, no provider abstraction. `base_url` + `model` + `api_key` reaches
OpenAI, Groq, Azure OpenAI, and self-hosted servers (faster-whisper-server,
LocalAI, vLLM) through one integration.

*Rejected:* a vendor SDK. It would have delivered native speaker diarization — an
unstarted Phase 6 item — but costs lock-in and offers no self-hosted path, making
it the option least likely to help someone who cannot deploy locally. *Rejected:*
a provider seam built before a second implementation exists to shape it.

### 3.2 `whisper_task="translate"` is UNSUPPORTED on this backend

`/audio/translations` does not reliably report the **source** language, and
`detected_language` has two consumers:

| Consumer | Effect of a wrong value |
|---|---|
| `ocr/rapid_ocr.py:173` — `resolved_iso = detected_language or "en"` | wrong OCR model selected when `ocr_language="auto"` |
| `pipeline.py:228` — `Transcript(language=detected_language)` | wrong language recorded in the output |

Translation *is* a shipped local feature, so this is a real capability gap. It is
declared and enforced rather than silently degraded.

### 3.3 Compress before upload; do not chunk

`audio.py:33-45` extracts 16 kHz mono WAV ≈ **1.92 MB/min**, so a 25 MB provider
cap is reached at **≈13 minutes** — most content for a video tool with playlist
support, not an edge case.

Opus at 24 kbps ≈ **10.8 MB/hour**, moving the ceiling to **≈2.3 hours** at 25 MB.

Chunking was rejected: it requires silence detection to avoid splitting mid-word,
exact offset arithmetic the merge stage depends on, a rule for which chunk's
language wins, and N× billing. Compression needs none of those. `ffmpeg` is
already a hard dependency.

### 3.4 Config-selected factory (Approach A)

`build_asr_engine(config) -> AsrEngine`, called from `pipeline.py`. Chosen over an
inline conditional (duplicated at two sites, and any third site silently misses
the branch) and over a plugin registry (no beneficiary; YAGNI).

The challenge promoted this from "possibly unnecessary indirection" to
**load-bearing** — see §5.

## 4. Architecture

| File | Change |
|---|---|
| `config.py` | new fields, `base_url` normalization, optional validator |
| `asr/factory.py` | **new** — `build_asr_engine(config) -> AsrEngine` |
| `asr/openai_compatible.py` | **new** — `OpenAICompatibleTranscriber` |
| `audio.py` | **new** — `compress_for_upload()` |
| `pipeline.py` | two sites (`:134`, `:167`) call the factory |
| `pyproject.toml` | new `[remote]` extra |

**Configuration — seven fields, all `PANO_`-prefixed, all defaulting to today's behaviour:**

```
asr_backend       Literal["local", "openai_compatible"] = "local"
asr_base_url      str | None          (trailing slash normalized)
asr_model         str | None
asr_api_key       SecretStr | None    (environment only)
asr_timeout_s     float = 120.0
asr_max_retries   int = 2
asr_upload_codec  Literal["opus", "none"] = "opus"
```

**Separation of concerns.** ffmpeg work stays in `audio.py`; HTTP stays in the
backend. The backend never shells out; `audio.py` never knows a network exists.
Each is testable alone — the transcoder against a fixture file, the backend
against a mocked transport.

**Data flow.** Extract WAV (unchanged, stays local as the source of truth) →
`compress_for_upload()` into `temp_dir` → POST multipart to
`{base_url}/audio/transcriptions` with `response_format=verbose_json` → parse and
normalize → `(segments, detected_language)`, identical in shape to what
`WhisperTranscriber` returns today. Timestamps arrive absolute; nothing is
stitched or offset.

## 5. Enforcement — three points, and why one is not enough

**This is the defect the challenge caught, and it would have shipped.**

`cli.py:167-168` and `api/server.py:154` both apply overrides via
`config.model_copy(update=updates)`. **Pydantic v2's `model_copy()` does not
re-run validators.** A `model_validator(mode="after")` on config therefore
catches only the `PANO_WHISPER_TASK=translate` environment route — `--translate`
and API `{"translate": true}` bypass it entirely and reach the remote backend.

A guard that fires on one of three paths is worse than no guard, because it reads
as protection.

| Point | Enforces | Necessity |
|---|---|---|
| `build_asr_engine` | translate+remote, missing `base_url`/`model`/`api_key` | **Mandatory** — the only choke point `model_copy` cannot bypass |
| config `model_validator` | same, for the env route | Optional; early, friendlier feedback |
| `api/server.py`, pre-`model_copy` | `translate=true` under a remote backend → HTTP 400 | Required, or the failure surfaces as a background-job error rather than a request error |

The mandatory point is inside the factory. That is what makes §3.4 load-bearing
rather than stylistic.

## 6. Response contract

### 6.1 The `language` field is not ISO 639-1

Verified against OpenAI's official OpenAPI specification. The response schema
constrains `language` only to `type: string`, and the specification's own example
returns:

```json
{ "task": "transcribe", "language": "english", "duration": 8.47, ... }
```

Meanwhile the **request** parameter is documented as ISO-639-1. The API is
asymmetric. `_ISO_TO_LANGREC` (`ocr/rapid_ocr.py:118-148`) is keyed on two-letter
codes, so `"english"` misses the map and `rapid_ocr.py:172-180` falls back to
`LangRec.EN` with only a warning — silent degradation on the *supported*
transcribe path.

### 6.2 Normalization rule — normalize the format, never the content

1. A two-letter value is taken as ISO 639-1 and passed through.
2. A longer value is lower-cased and looked up in a name→code table.
3. Anything unrecognised is a **hard error** naming the received value and
   directing the user to set `whisper_language` explicitly.

**A well-formed code that `_ISO_TO_LANGREC` does not know is passed through
unchanged, not rejected.** The local path warns and falls back to `EN` for those,
and the remote backend must not be *stricter* than local — that would be a
behaviour difference dressed up as safety. We normalize representation; we do not
adjudicate which languages are supported.

### 6.3 Other response handling

- `segments` is **not** in the schema's `required` set (only `language`,
  `duration`, `text` are), which makes the absence check necessary rather than
  defensive: key absent or unparseable → hard error.
- `segments: []` is a **valid empty result** — genuinely silent audio. The local
  path returns `[]` at `pipeline.py:137` for the no-audio branch. Empty and
  malformed must not be conflated.
- `asr_logprob` ← the segment's `avg_logprob` when present, else `None`. **Never
  a 0-1 confidence**, which would collide with the OCR confidence scale.
- Per-segment `language` ← the normalized ISO code. `source` stays `"SPEECH"`.
- Parse into a **pydantic response model**, not hand-rolled dict access: `mypy`
  runs `strict` with `warn_return_any` (`pyproject.toml:160-165`) and
  `response.json()` is `Any`. This also collapses malformed and
  missing-timestamp handling into one validated path.

## 7. Dependencies

`httpx` is currently **dev-only** (`pyproject.toml:71`); `merge/llm_cleanup.py`
receives it transitively via `ollama`. Shipping without addressing this would
leave CI green while `pip install panoscribe` users hit `ImportError`.

- Add a `[remote]` extra carrying `httpx`.
- Guard the import following the established pattern at
  `merge/llm_cleanup.py:59-67`: module-top `try/except ImportError`, bind to
  `None`, `# pragma: no cover`, and raise a deferred, actionable `PanoScribeError`
  at point of use. **Module scope is load-bearing** — every test in this
  repository patches at the import site.
- Update CI and `CLAUDE.md`'s bootstrap line
  (`uv sync --extra dev --extra api`) **together**, or the tests cannot import
  their subject.

## 8. Error handling

| Condition | Behaviour |
|---|---|
| translate + remote | Refuse at all three points in §5 |
| missing `base_url` / `model` / `api_key` | Refuse in the factory, naming the env var |
| 401 / 403 | Auth error; **never echo the key** |
| 413 | "the server or a proxy in front of it rejected the upload as too large" — naming `asr_upload_codec`. Do **not** cite 25 MB: self-hosted servers have no such cap, and nginx defaults `client_max_body_size` to 1 MB, so a proxy is the likelier culprit |
| 429 / 5xx / timeout | Bounded retry, honouring `Retry-After` |
| other 4xx | Immediate failure, no retry |
| unparseable / missing `segments` | Hard error |
| `segments: []` | Valid empty result |
| unnormalizable `language` | Hard error (§6.2) |
| ffmpeg without libopus | Actionable error naming `asr_upload_codec=none` — not a raw stderr tail |

There is deliberately **no client-side size cap**. A cap is a guess about a remote
server; self-hosted targets have none, so a 25 MB default would produce false
failures on exactly the deployment §3.1 exists to serve.

**Privacy notice.** A single INFO line is the wrong level:
`_quiet_pipeline_logging` (`pipeline.py:246-252`) raises the `panoscribe` logger
to WARNING for a whole batch, so the notice would vanish across `transcribe_many`
— the highest-volume upload case. Emit at WARNING, or once from the factory
outside the quieted region.

## 9. Documentation deliverables

The user asked specifically that caveats and restrictions be documented clearly.
This is a deliverable, not a footnote.

- **README** — an opt-in section stating plainly that **user audio leaves the
  machine** and is sent to a third-party provider; the `translate` restriction;
  the ~2.3 h practical ceiling with its arithmetic.
- **#85 spans three places, not one:** `README.md:100` ("Fully local" →
  "local by default"), plus `:104` and `:134`, which document `--translate`
  without qualification. `IMPLEMENTATION_PLAN.md:288,347` carry the same claim.
  Per #85 this ships **in the same PR** as this backend — never before.
- **Config field docstrings** covering each new field.
- **Error messages are documentation.** Every refusal names the remedy.
- **CHANGELOG.**

## 10. Testing

- Protocol conformance — `isinstance` against `AsrEngine`, mirroring
  `tests/test_ocr_protocol.py`.
- Backend behaviour via `httpx.MockTransport`: success, 401, 413, 429-with-retry,
  timeout, malformed body, missing timestamps, `segments: []`.
- **`--translate` and API `translate:true` each need a dedicated rejection test.**
  These are the `model_copy` paths from §5; the regression risk is the entire
  feature.
- `language` normalization: two-letter passthrough, full-name mapping,
  unrecognised → error, and a well-formed-but-unknown code passing through.
- `base_url` trailing-slash round trip.
- Secret-leak assertion — key absent from config `repr` and from emitted log
  records.
- **`tests/test_cli.py:116` must change.** It patches
  `panoscribe.pipeline.WhisperTranscriber`; once the pipeline calls the factory
  that patch goes inert and the real transcriber runs. It becomes
  `patch("panoscribe.pipeline.build_asr_engine")`, and the docstring at
  `test_cli.py:100-111` needs updating.
- `tests/test_whisper.py` must pass **unchanged** — if it needs edits, the seam
  was used wrongly.
- Patch the backoff sleep, or retry tests slow the suite.
- Gate green, including the 95% coverage floor (`pyproject.toml:190-194`, no
  `omit`, so the new module counts fully). Every retry and error branch needs a
  test to clear it — budget for that rather than meeting it at gate time.

## 11. Deliberate non-decisions

- **No shared abstraction with #84.** The issue speculates the two "may share one
  abstraction". OCR already has its own protocol. If a shared seam is right, it
  will be visible once a second implementation exists — designing it against one
  is how seams end up fitting the second case badly.
- **`SecretStr` is sufficient today** and was verified, not assumed:
  `model_dump` appears only at `scripts/eval_ocr.py:307,313` on a result object,
  never on config, and no log call takes `config` or `repr(config)`. Two standing
  conditions: no `.get_secret_value()` inside any log or error string, and no API
  response path serializing config. The leak test in §10 is what keeps this true.
- **Stale docstring, fix in passing.** `pipeline.py:117-119` claims tests patch
  `panoscribe.cli.WhisperTranscriber`; the live target is `panoscribe.pipeline.`.

## 12. Known risks

1. **Provider variance is the central bet.** "OpenAI-compatible" is a convention,
   not a standard. §6.2's normalization and §8's error table are what convert
   variance into loud failures instead of quiet ones, but a provider returning a
   materially different `verbose_json` shape will need its own handling.
2. **Cost is not surfaced.** Nothing estimates or reports spend. Acceptable for
   ASR (one upload per clip) and explicitly noted as unaddressed; it is the
   central problem for #84, not here.
3. **Demand is unmeasured** (§1).
4. **Diarization note, not scope.** OpenAI now lists a
   `gpt-4o-transcribe-diarize` model, though it does not support
   `timestamp_granularities`. Relevant to the Phase 6 diarization item; out of
   scope here, recorded so the connection is not lost.

## 13. Provenance

Decisions 3.1-3.4 and Approach A were taken with the user on 2026-09-02.
The design was then challenged by the `architect` agent over two passes
(scope/necessity, then correctness/completeness), which produced three blocking
findings — §5, §6.1, §7 — and cut the configuration surface from eight fields to
seven, plus one value (`flac`) from `asr_upload_codec`. (The challenge report
said "8 → 6"; recounting against the field list gives seven, since `flac` is a
value rather than a field. Noted because an uncorrected count in a spec is the
kind of small wrongness that gets quoted downstream.) Every load-bearing claim
cited here was verified at source: the
`model_copy` bypass in `cli.py` and `api/server.py`, `httpx`'s dev-only scope,
the `test_cli.py` patch target, and the `language` field format against OpenAI's
published OpenAPI specification.
