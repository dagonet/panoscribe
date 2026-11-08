[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/dagonet/panoscribe)
[![CI](https://github.com/dagonet/panoscribe/actions/workflows/ci.yml/badge.svg)](https://github.com/dagonet/panoscribe/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11 | 3.12](https://img.shields.io/badge/Python-3.11_%7C_3.12-blue.svg)](https://www.python.org/downloads/)
[![Status: In Development](https://img.shields.io/badge/Status-In%20Development-orange.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

# panoscribe

**Extract complete transcripts from any video — speech AND on-screen text, combined.**

Existing transcription tools only capture what's *spoken*. But video creators — on TikTok, YouTube, Instagram, and beyond — pack critical information into **on-screen text overlays**: instructions, captions, labels, commentary that never appears in audio-only transcripts. panoscribe combines **speech recognition (ASR)** with **on-screen text extraction (OCR)** to produce a unified, timestamped transcript that captures *everything*.

## How It Works

```
Video URL (TikTok, YouTube, Reels, Shorts, ...) or local file
        │
        ├──▶ Audio ──▶ faster-whisper (large-v3-turbo) ──▶ Speech transcript
        │
        └──▶ Frames ──▶ RapidOCR (GPU via ONNXRuntime) ──▶ On-screen text
                                                    │
                              ┌──────────────────────┘
                              ▼
                    Merge + Deduplicate
                              │
                              ▼
                   Unified Transcript
              [SPEECH] + [ON-SCREEN] + [BOTH]
```

## Quick Start

```bash
# Install
uv pip install panoscribe

# Transcribe a TikTok
panoscribe transcribe https://www.tiktok.com/@user/video/123456

# YouTube video
panoscribe transcribe https://www.youtube.com/watch?v=abc123

# Instagram Reel
panoscribe transcribe https://www.instagram.com/reel/xyz789

# Local file
panoscribe transcribe ./video.mp4 --format json --output transcript.json

# Speech-only (no OCR)
panoscribe transcribe <url> --no-ocr

# SubRip subtitles
panoscribe transcribe ./video.mp4 --format srt --output transcript.srt

# Markdown digest
panoscribe transcribe ./video.mp4 --format md --output transcript.md

# LLM-cleaned OCR (opt-in; requires `uv sync --extra llm` + running Ollama)
panoscribe transcribe ./video.mp4 --ocr --llm-cleanup --output transcript.json

# LLM punctuation cleanup on speech segments (opt-in; same extras + Ollama)
panoscribe transcribe ./video.mp4 --llm-cleanup --asr-cleanup --output transcript.md

# Batch — one URL per line in urls.txt; outputs land in transcripts/
panoscribe transcribe-many urls.txt --output-dir transcripts/ --format md

# Batch a whole YouTube channel or playlist (auto-expanded inline)
echo "https://www.youtube.com/@channel/videos" > urls.txt
panoscribe transcribe-many urls.txt --output-dir transcripts/ --format md

# Speech translation: transcribe German speech as English text
panoscribe transcribe ./video.mp4 --translate --output transcript.json
```

Playlist + channel URLs in the URL list are automatically expanded via yt-dlp;
mix freely with single-video URLs and local file paths in the same `urls.txt`.

Re-running `transcribe-many` with the same `--output-dir` resumes from
`{output_dir}/.panoscribe-batch-state.json` — completed items are skipped, and
`pending`/`failed` items are re-attempted. Delete the state file to start fresh.

## Supported Platforms

panoscribe uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) under the hood, which supports **hundreds of platforms** out of the box. The ASR and OCR pipeline is fully platform-agnostic. Platform-specific **UI filtering profiles** (to exclude like buttons, share icons, etc. from OCR) are provided for:

- ✅ TikTok
- ✅ YouTube / YouTube Shorts
- ✅ Instagram Reels
- 🔲 Twitter/X (Phase 6 backlog)
- 🔲 Facebook (Phase 6 backlog)

Videos from any other platform work too — just without UI-specific filtering.

## Features

- **Dual extraction** — Speech (ASR) + on-screen text (OCR) combined into one transcript
- **Smart deduplication** — Detects when spoken words match displayed text, avoids duplicates
- **Platform-aware** — UI element filtering profiles for TikTok, YouTube, Instagram
- **Local by default** — The default install and config do all inference on your machine, with no API keys or cloud services. Remote speech recognition is an explicit opt-in, switched on only by settings with no defaults. When it is on, **your audio leaves the machine** and goes to the provider you configured. See [Remote speech recognition](#remote-speech-recognition-opt-in).
- **GPU-accelerated** — Optimized for NVIDIA GPUs (CUDA), works on CPU too
- **Multiple output formats** — JSON, TXT, SRT, Markdown
- **Multilingual** — Supports 80+ languages for both speech and text recognition
- **Speech translation** — Translate speech from any supported language directly into English with `--translate` (uses Whisper's native `task=translate`). On-screen text stays in the source language.
- **LLM OCR cleanup (optional)** — Fix OCR artefacts on screen-text segments via a local Ollama model. Opt-in with `--llm-cleanup`. Requires `uv sync --extra llm` and a running Ollama with the configured model pulled (default `llama3.2:3b`).
- **LLM ASR punctuation cleanup (optional)** — Improve punctuation and capitalization on speech segments via a local Ollama model. Opt-in with `--asr-cleanup`. Reuses the same `[llm]` extras and Ollama host as OCR cleanup.

## TikTok Photo Posts

TikTok ``/photo/`` posts are image slideshows with optional audio. yt-dlp cannot
download these; panoscribe uses **gallery-dl** instead.

```bash
# Install with the photo extra
uv sync --extra photo

# Transcribe a TikTok photo post (auto-detected)
panoscribe transcribe https://www.tiktok.com/@user/photo/1234567890

# Process a local directory of slides + optional audio
panoscribe transcribe ./my-photo-dir/
```

**Timestamp semantics:** When the photo post has an audio track, slides are evenly
spread across the audio duration (slide i of n gets timestamp i/n through
(i+1)/n of total duration). Without audio, each slide gets a 1-second index-based
window (slide 0: 0-1s, slide 1: 1-2s, ...). The OCR runs at native resolution on
each slide, unlike stitched-video processing where resolution is constrained by
the video codec (see #46 and #41 for benchmarks — native slides yield ~56
detection boxes vs ~17 on stitched frames).

## Translation

When using ``--translate`` (or ``PANO_WHISPER_TASK=translate``), Whisper transcribes
source-language speech directly into English. Segment-level ``language`` fields
report ``en`` (the text language), while the top-level transcript ``language`` field
retains the detected source language — this ensures OCR language auto-resolution
still works on on-screen text, which stays in the source language. Cross-language
``[BOTH]`` merges do not fire under translation (WRatio < 0.85 between English
speech and source-language OCR), so segments remain ``[SPEECH]`` + ``[ON-SCREEN]``.

## API Mode (HTTP Server)

panoscribe provides an HTTP API for submitting transcription jobs and polling
for results. The server is single-worker (one job at a time) and uses the same
pipeline as the CLI.

```bash
# Install with the API extra
uv sync --extra api

# Start the server (default: http://127.0.0.1:8000)
panoscribe serve

# Custom host/port
panoscribe serve --host 127.0.0.1 --port 9000
```

### Endpoints

```bash
# Health check
curl http://127.0.0.1:8000/healthz
# {"status":"ok","version":"..."}   # reports the installed panoscribe package version

# Submit a job
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"source": "https://www.youtube.com/watch?v=abc123"}'
# {"job_id":"a1b2c3d4e5f6..."}

# With overrides (same flags as the CLI)
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"source": "video.mp4", "language": "de", "translate": true, "ocr": false}'

# Poll for results
curl http://127.0.0.1:8000/jobs/a1b2c3d4e5f6...
# {"id":"a1b2c3...","source":"...","status":"done","result":{...}}

# List all jobs (summary only)
curl http://127.0.0.1:8000/jobs
# [{"id":"a1b2c3...","source":"...","status":"done","created_at":"..."}]
```

### Security

The API has **no authentication** and triggers downloads of arbitrary URLs. It
binds to `127.0.0.1` by default. **Do not expose it publicly** — bind to
localhost or use a reverse proxy with authentication.

### v1 Limitations

- **No persistence**: restarting the server loses all in-progress and completed
  jobs. Results should be saved externally by the caller.
- **Shutdown hang**: Ctrl+C blocks until the current job finishes (non-daemon
  threads). In-flight jobs are lost — there is no graceful handoff.
- **No cancellation**: once submitted, a job runs to completion or failure.
- **Single worker**: one GPU means one job at a time.
- **JSON output only**: the API always returns JSON results regardless of the
  CLI's ``--format`` flag.
- **Poll-based**: no SSE, no webhooks — poll ``GET /jobs/{id}``.

## Known Limitations

panoscribe is in active development (alpha). The pipeline produces a usable
combined transcript on most short-form videos. The most visible current
constraint is documented below; the full set of tracked limitations and
planned improvements lives in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
under **Phase 6 — Advanced Features** (single source of truth for what is
being worked on).

### OCR noise on text-heavy backgrounds

Videos with persistently visible background text — diplomas/certificates on
a wall, dense channel-branding overlays, on-set documents — produce per-frame
OCR detections that vary slightly between frames (different bounding-box
slicing, different sub-word fragments). Each variant lands in its own
canonical-text bucket, defeats cross-frame dedup, and survives the UI
frequency filter (because no single canonical string repeats often enough
to cross the threshold). The result is dozens of sub-second `[ON-SCREEN]`
artifact segments mixed in with real captions.

The real captions still cluster correctly into multi-second `[ON-SCREEN]`
segments. The noise sits alongside them.

**Workarounds today:**
- `--no-ocr` — speech-only transcript. Fastest if you don't need on-screen
  text at all.
- Post-process the JSON output: `jq '.segments |= map(select(.end - .start
  >= 1.0))'` (or equivalent) drops sub-second artifacts and keeps the
  multi-second clusters that represent real captions. The `|=` form
  preserves the wrapping object (language, source path metadata); plain
  `|` would flatten to just the filtered array.
- Tune `PANO_OCR_MIN_CONFIDENCE` (default `0.6`) higher to suppress
  low-confidence partial detections, at the cost of also missing some real
  text.
- The `PANO_OCR_DET_LIMIT_SIDE_LEN` / `PANO_OCR_DET_THRESH` / `PANO_OCR_DET_BOX_THRESH` env overrides expose RapidOCR's detection-model knobs for experimenting with dense-small-text content (defaults tuned for caption overlays). Model-variant overrides (`PANO_OCR_{DET,REC}_{MODEL_TYPE,OCR_VERSION}`) switch to other models, per task: `PP-OCRv4`, `PP-OCRv5` or `PP-OCRv6`, and model types `mobile` / `server` (v4, v5) or `tiny` / `small` / `medium` (v6). A knob that does not fit its version (for example `PANO_OCR_DET_MODEL_TYPE=medium` with PP-OCRv4) stops OCR for that item when it starts (after the download and speech recognition) with an error that names the setting or the language, and what is allowed. With server / PP-OCRv5 detection there is an automatic CH-det-lang override (registry limitation — only `ch_*` det models ship for server/v5). `PANO_OCR_DET_LANG` (`en` | `ch` | `multi`) selects the detection model independently of the recognition language; for Latin-script text the default `en` (`en_PP-OCRv3_det_mobile`) is retained after a Sprint 13 A/B, and `multi` (`multi_PP-OCRv3_det_mobile`, the multilingual detector) is an opt-in for hard / low-recall latin-script content — it trades ~3–5× more raw detections for a small quality edge, so it is not the default (see [`docs/plans/2026-07-16-ocr-det-ab.md`](docs/plans/2026-07-16-ocr-det-ab.md)). Under the `v6` model set (see [OCR model sets](#ocr-model-sets)), setting `PANO_OCR_DET_LANG` keeps detection on the classic model, because the v6 detector has no `multi`; if you pin the detector to PP-OCRv6 with `PANO_OCR_DET_OCR_VERSION`, only `en` and `ch` are valid there.

## Docker

```bash
# Build
docker build -t panoscribe .

# GPU transcription
docker run --gpus all --rm -v ./output:/output panoscribe transcribe \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -o /output/transcript.json

# CPU-only (override defaults)
docker run --rm -e PANO_WHISPER_DEVICE=cpu -e PANO_WHISPER_COMPUTE_TYPE=int8 \
  -e PANO_OCR_DEVICE=cpu panoscribe transcribe ./video.mp4 -o /output/transcript.json
```

The image bundles Whisper `large-v3-turbo` (~1.5 GB) and RapidOCR models (~66 MB:
the default `classic` models for English, Latin-script and Chinese text, plus the
`v6` small set), so transcription of those languages starts instantly with no
model downloads at runtime. Other OCR languages download their models
on first use. The `[photo]`
extra (gallery-dl) is included, so TikTok `/photo/` posts work in-container.
The `[llm]` extra is **not** bundled — LLM cleanup (`--llm-cleanup` / `--asr-cleanup`)
targets a host-local Ollama server and is intended for non-container installs.
GPU passthrough requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

## Requirements

- Python 3.11 or 3.12
- NVIDIA GPU with CUDA 12.x (recommended, 8+ GB VRAM). Verify: `python -c "import onnxruntime as ort; print(ort.get_available_providers())"` — should list `CUDAExecutionProvider`
- ffmpeg
- Docker 20.10+ (optional — for containerized deployment)

On Windows, CUDA 12 runtime libraries (cuda_runtime, cublas, cudnn, cufft) are bundled via pip — no separate CUDA toolkit install required. A system CUDA install, if present, is not used.

Model downloads, offline setups, and CUDA errors are covered in
[docs/troubleshooting.md](docs/troubleshooting.md).

## OCR model sets

Which OCR models run is chosen by one setting, `PANO_OCR_MODEL_SET` (`--ocr-language` and `PANO_OCR_LANGUAGE` still pick the language):

- **`classic`** (default; empty also means `classic`) — rapidocr's PP-OCRv4 mobile route, the same model files as before for English, Latin-script and Chinese text. Recognition for Eastern Slavic (`eslav`), Thai and Greek uses PP-OCRv5 mobile, because PP-OCRv4 has no model for them.
- **`v6`** (opt-in) — PP-OCRv6 `small`, picked per language. A language with no PP-OCRv6 model falls back to the classic models, with one INFO line in the log.

Switch with `export PANO_OCR_MODEL_SET=v6` (or put it in your `.env`). The explicit `PANO_OCR_{DET,REC}_*` knobs (see [OCR noise on text-heavy backgrounds](#ocr-noise-on-text-heavy-backgrounds)) still win over the set, per task.

`classic` is the default because it was measured, not assumed. On 15 real clips in five languages (German, English, French, Spanish, Portuguese), `v6` found about 3 points less of the expected text in French (two French clips, 97 texts; about one text beyond the allowed margin) and left more unmatched text in French and Portuguese; it was equal or slightly cleaner in German and English, and about 1.3× slower on CPU. See [`docs/plans/2026-11-08-ocr-v6-measurement.md`](docs/plans/2026-11-08-ocr-v6-measurement.md) for the numbers.

panoscribe requires `rapidocr[rtl]>=3.10,<3.11`; the `rtl` extra pulls in `python-bidi`, which rapidocr needs for Arabic. The languages Japanese, Korean, Russian (and other Eastern Slavic), Cyrillic, Arabic, Hindi (Devanagari), Thai, Greek, Tamil, Telugu and Kannada now start; on the previous rapidocr they failed with `Invalid OCR configuration`. Korean, Hindi and Telugu start but read poorly on a synthetic check.

Known limitations: Arabic text comes out in display order ([#188](https://github.com/dagonet/panoscribe/issues/188)); AV1 videos that OpenCV cannot decode stop with a clear error (see [Troubleshooting](docs/troubleshooting.md#cannot-decode-any-video-frame-av1)).

## Running without a GPU

Both `whisper_device` and `ocr_device` default to `"cuda"` and fail fast with a
named remedy if no CUDA-capable device is found (see
[docs/troubleshooting.md#cuda-not-found](docs/troubleshooting.md#cuda-not-found)).
To run entirely on CPU, set:

```bash
export PANO_WHISPER_DEVICE=cpu
export PANO_WHISPER_COMPUTE_TYPE=int8
export PANO_OCR_DEVICE=cpu
```

`PANO_WHISPER_COMPUTE_TYPE` matters here: the default, `float16`, is a
GPU-only compute type and is not valid on CPU — always pair
`PANO_WHISPER_DEVICE=cpu` with `PANO_WHISPER_COMPUTE_TYPE=int8`.

The default ASR model, `large-v3-turbo`, is noticeably slow on CPU. For CPU
runs, `PANO_WHISPER_MODEL=small` is the practical choice — it was used to
verify this section end-to-end (`PANO_WHISPER_DEVICE=cpu
PANO_WHISPER_COMPUTE_TYPE=int8 PANO_OCR_DEVICE=cpu PANO_WHISPER_MODEL=small`
against a 13-second local fixture): both the ASR and OCR stages ran on CPU
(confirmed from the logs: `Loading Whisper model small on cpu
(compute_type=int8)`) and produced a transcript with both `SPEECH` and
`ON-SCREEN` segments.

Measured on this machine (Windows, CPU-only path, models pre-cached so the
timing excludes the one-time download): the 13-second clip took **~10
seconds** wall-clock end-to-end with `small`, i.e. close to realtime. This
is a CPU-only measurement — the equivalent GPU run on this fixture was not
timed, so no CPU-vs-GPU speedup ratio is claimed here. `large-v3-turbo` is a
substantially larger model than `small` and was not benchmarked on CPU;
expect it to be markedly slower per the model-size difference alone.

## Remote speech recognition (opt-in)

Speech recognition can run on a server instead of your machine, for example
when you cannot deploy models locally. Local inference stays the default and
the recommended path.

**When this is on, your audio leaves the machine** and is sent to the server
you configured. panoscribe logs one warning naming that host the first time.
Nothing else switches it on, and there is no fallback: a failed remote run
fails, and a local run never silently goes remote.

Install the supported dependency, then set the three settings that switch it
on (there are no defaults for the URL or the model) and, if the server needs
one, an API key:

```bash
uv sync --extra remote-asr

export PANO_ASR_BACKEND=remote
export PANO_ASR_REMOTE_BASE_URL=https://asr.example.com/v1
export PANO_ASR_REMOTE_MODEL=whisper-1
export PANO_ASR_REMOTE_API_KEY=...   # optional for self-hosted servers
```

`uv sync` keeps only the extras you name, so list the others you use as well,
for example `uv sync --extra remote-asr --extra api`.

The extra only installs `httpx`; the settings are what enable the backend.
They are environment or `.env` only, with no command-line flags, so a key
never lands in shell history. See
[docs/configuration.md](docs/configuration.md#remote-asr) for timeouts,
retries and the upload limit.

What the server must provide:

- An OpenAI-compatible `POST {base_url}/audio/transcriptions` endpoint.
- A model that returns `verbose_json` with segment timestamps, such as
  `whisper-1`-style models. `gpt-4o-transcribe`-style models do not return
  segment timestamps and will not work.
- Audio over the upload limit (25 MB by default, about 13 minutes) is split
  at quiet points and sent in order, so long videos work.

Limits:

- `--translate` is not supported with the remote backend and fails before any
  audio is sent.
- Environment proxy settings are honoured, except for a loopback server. A
  loopback server also ignores `SSL_CERT_FILE` and `SSL_CERT_DIR`, so
  `https://localhost` with a private CA is not supported.
- OCR stays local. A machine that cannot run local models also needs
  `--no-ocr` or `PANO_OCR_DEVICE=cpu`.
- The HTTP API server cannot change these settings per job; they come from
  the server's own environment.

## Renamed from OmniScribe

This project was called **OmniScribe** and is now **panoscribe**. The `omniscribe` name
on PyPI belongs to an unrelated project (*SoberMind Offline Session Transcriber*), so
this project could never be published under it — `pip install omniscribe` gets you
different software.

What changed for anyone running from source:

- Install command: `uv pip install panoscribe` (was `uv pip install omniscribe`)
- CLI command: `panoscribe` (was `omniscribe`)
- Environment variables: `PANO_*` (was `OMNI_*`), e.g. `PANO_WHISPER_DEVICE`

The GitHub repository URL redirects from the old name, so existing links keep working.

## Status

🚧 **Under active development** — See [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for the roadmap.

## License

MIT
