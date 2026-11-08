# Troubleshooting

## Model downloads on first run

panoscribe does not bundle models outside the Docker image. On first run
(non-container installs), the two backends pull their weights
automatically:

- **faster-whisper** downloads the configured `PANO_WHISPER_MODEL`
  (default `large-v3-turbo`) from Hugging Face Hub — roughly **1.6 GB**.
- **RapidOCR** downloads its detection/recognition models from
  `modelscope.cn`, not from Hugging Face. The default `classic` set is roughly
  **10 to 15 MB** for English, Latin-script or Chinese text (each other
  language downloads its own models the first time you use it, usually a
  recognition model and the multilingual detector);
  the `v6` set (`PANO_OCR_MODEL_SET=v6`) is roughly **30 MB**.

Both are cached after the first run, so subsequent runs do not re-download.
RapidOCR keeps its models in the `rapidocr/models` folder inside the
installed package (`site-packages`), so reinstalling or upgrading `rapidocr`
can bring the download back.
The Docker image (`Dockerfile`) pre-downloads the Whisper model and the
RapidOCR models for English, Latin script and Chinese plus the `v6` set
(about 66 MB) at build time, so containerized runs for those languages never
hit the network for models.

If the OCR models cannot be downloaded (for example `modelscope.cn` is
blocked), OCR fails at start for that item with
`Failed to initialize RapidOCR on <device>: ...`, and the cause is in the
message. In a `transcribe-many` batch the other items carry on. See
*Offline pre-seeding* below to fetch the models somewhere that has network
access.

### Using a Hugging Face mirror (`HF_ENDPOINT`)

If `huggingface.co` is slow or blocked from your network, point the
Hugging Face client at a mirror before running panoscribe:

```bash
export HF_ENDPOINT=https://hf-mirror.com
panoscribe transcribe ./video.mp4 -o transcript.json
```

### Relocating the cache (`HF_HOME`)

By default, Hugging Face caches downloaded models under a per-user cache
directory. To relocate it (e.g. to a shared volume or a drive with more
space):

```bash
export HF_HOME=/path/to/cache
panoscribe transcribe ./video.mp4 -o transcript.json
```

Set `HF_HOME` before the first run so the Whisper download lands there.
`HF_HOME` and `HF_ENDPOINT` do not affect RapidOCR: its models come from
`modelscope.cn` and are stored in the `rapidocr/models` folder inside the
installed package.

### Offline pre-seeding

To avoid a network dependency at run time (air-gapped environments, CI),
pre-download both models once on a machine with network access, then copy
them to the target machine.

Whisper (Hugging Face cache, relocatable with `HF_HOME`):

```bash
HF_HOME=./model-cache python -c \
  "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"

# Copy ./model-cache to the target machine, then:
export HF_HOME=/path/to/model-cache
```

RapidOCR 3.10 loads its models lazily, so creating `RapidOCR(...)` alone
downloads nothing. Run panoscribe once on a short clip with sound (speech
recognition runs first and needs an audio track), with the language and
model set you will use; OCR start-up then fetches the models it needs. One
run seeds both the Whisper cache (`HF_HOME`) and the OCR models:

```bash
HF_HOME=./model-cache PANO_WHISPER_DEVICE=cpu PANO_WHISPER_COMPUTE_TYPE=int8 \
  PANO_OCR_DEVICE=cpu PANO_OCR_MODEL_SET=classic \
  panoscribe transcribe ./short.mp4 --ocr-language en -o out.json

# Find the folder to copy to the same place on the target machine:
python -c "import pathlib, rapidocr; print(pathlib.Path(rapidocr.__file__).parent / 'models')"
```

Repeat with `--ocr-language <code>` for every other language you need
(each downloads its own models). One extra run with `PANO_OCR_MODEL_SET=v6`
covers every v6 language, because they share one detector and one
recogniser. The Dockerfile pre-downloads RapidOCR models the same way, by
forcing the model load at build time.

## CUDA not found

If `PANO_WHISPER_DEVICE=cuda` or `PANO_OCR_DEVICE=cuda` (the defaults) and
no CUDA-capable device is available, panoscribe fails fast at model-load
time with an error naming the exact remedy, e.g.:

```
ASR (CTranslate2): No CUDA-capable device was found. Run on CPU instead: set
PANO_WHISPER_DEVICE=cpu and PANO_WHISPER_COMPUTE_TYPE=int8 for ASR, and
PANO_OCR_DEVICE=cpu for OCR. See docs/troubleshooting.md#cuda-not-found for
details.
```

(or the `OCR (ONNXRuntime): ...` variant for the OCR path). See
[Running without a GPU](../README.md#running-without-a-gpu) for the full
CPU env-var set.

This check only detects an **absent CUDA runtime** — it does not catch
every GPU misconfiguration. The most common Windows failure mode is a
broken cuDNN sub-library resolution (`cublas64_12.dll` / `cudnn64_9.dll`
not found even though a CUDA-capable card is present); that failure is
currently `DEBUG`-only in `src/panoscribe/asr/whisper.py` and surfaces as
a raw CTranslate2 error rather than the friendly message above. If you see
a CTranslate2 or ONNXRuntime error mentioning a missing DLL or shared
library rather than the message above, run with `PANO_LOG_LEVEL=DEBUG` to
see the DLL-directory registration log, and confirm the `nvidia-cudnn-cu12`
/ `nvidia-cublas-cu12` wheels installed alongside `ctranslate2` (`uv pip
list | grep nvidia`).

## Install failures

- **macOS / Windows ARM / linux-aarch64**: these platforms resolve to the
  CPU build of ONNXRuntime automatically via `pyproject.toml` markers —
  there is no separate install incantation and no known resolver failure
  on any of them.
- **Python version**: panoscribe supports Python 3.11–3.13
  (`requires-python = ">=3.11,<3.14"` in `pyproject.toml`). If `uv sync` or
  `pip install` fails to resolve, check your interpreter version first
  (`python --version`).
- **`onnxruntime` / `onnxruntime-gpu` conflicts**: if you see import errors
  or provider-mismatch behavior after manually installing with plain
  `pip` (not `uv`), note that `pip` does not honor uv's
  `override-dependencies` table and can install both `onnxruntime` and
  `onnxruntime-gpu` into the same package directory. Prefer `uv sync`,
  or manually `pip uninstall onnxruntime onnxruntime-gpu` and reinstall
  only the one your platform needs.

## Stale uv cache right after a release

If you run `uv pip install panoscribe==<new version>` immediately after a
release and see:

```
No solution found ... no version of panoscribe==0.6.0
```

the package is very likely already published — `uv` served a stale cached
`simple-index` response for `pypi.org/simple/panoscribe/` (it may even log
`Found fresh response for: https://pypi.org/simple/panoscribe/` while doing
so). Confirm by checking `https://pypi.org/simple/panoscribe/` or
`https://pypi.org/pypi/panoscribe/json` directly — if the new version is
listed there, this is a client-side cache artifact, not a broken release.

Fix by bypassing the cache:

```bash
uv pip install --refresh --no-cache panoscribe==<new version>
# or
uv cache clean panoscribe
```

This has been observed on consecutive releases (0.5.0 and 0.6.0), resolving
correctly on retry both times.

## OCR fails to start (`Unsupported rec.lang_type`)

If OCR fails with an error such as:

```
Failed to initialize RapidOCR
ValueError: Unsupported rec.lang_type='latin' for PP-OCRv6 small model
```

you installed panoscribe 0.8.1 with `pip` or `uv pip install` and got
rapidocr 3.9 or newer. From 3.9 on, rapidocr's default recognition model has
no entry for most languages other than English, Chinese and Japanese.
panoscribe 0.8.1 did not cap the version. This applies to 0.8.1 only; later
releases pin a rapidocr range that works. Locked installs (`uv sync`,
Docker) were not affected.

Fix by upgrading panoscribe. 0.9.0 and newer fix this error (0.9.0 caps
rapidocr below 3.9); 0.10.0 moves to the newer library:

```bash
uv pip install --upgrade "panoscribe>=0.9.0"
```

## OCR fails to start with an explicit model setting

If you set one of `PANO_OCR_DET_MODEL_TYPE`, `PANO_OCR_REC_MODEL_TYPE`,
`PANO_OCR_DET_OCR_VERSION`, `PANO_OCR_REC_OCR_VERSION` or `PANO_OCR_DET_LANG`
and the run stops before the download (and before speech recognition runs)
with a message such as:

```
PANO_OCR_REC_MODEL_TYPE='medium' does not fit PP-OCRv4, PP-OCRv5 (the version in effect
for every OCR language with this model set and version setting); takes: mobile, server
```

or `OCR language 'eslav' has no PP-OCRv6 model; supported: ...`, the setting
does not fit the model that would run. panoscribe does not change an
explicit setting behind your back, so it stops and names the setting or the
language, and what is allowed. With a fixed `PANO_OCR_LANGUAGE` every such
problem is reported right at the start. With `PANO_OCR_LANGUAGE=auto`, a
setting that is wrong for every language is still reported at the start, while
one that depends on the detected language is reported when OCR starts (after the
download and speech recognition), with the same kind of message. The model types are `mobile` or `server` for PP-OCRv4 and
PP-OCRv5, and `tiny`, `small` or `medium` for PP-OCRv6. With the PP-OCRv6
detector pinned by `PANO_OCR_DET_OCR_VERSION`, `PANO_OCR_DET_LANG` must be
`en` or `ch`.

Fix by removing the setting (unset lets the model set decide), by
choosing a value from the message, or by switching `PANO_OCR_MODEL_SET`. See
[Configuration](configuration.md#ocr).

## Cannot decode any video frame (AV1)

```
Cannot decode any video frame from video.mp4 (codec: av01). ...
```

The video reader that panoscribe uses for OCR (OpenCV) can decode AV1 only with
hardware support, which most machines do not have
([#189](https://github.com/dagonet/panoscribe/issues/189)). Downloads now avoid
AV1 when the site offers another codec (the choice is otherwise yt-dlp's
default, so resolution still comes first) and use AV1 only when a video has
nothing else, so this mostly affects local AV1 files and the rare AV1-only
download. panoscribe checks
this right after the download, before speech recognition, and stops with the
error above. The error names the codec; the speech part is not affected.

Workarounds: re-encode the video to H.264 and run panoscribe on the new
file, for example

```bash
ffmpeg -i video.mp4 -c:v libx264 -crf 18 -c:a copy video-h264.mp4
```

or run with `--no-ocr` (`"ocr": false` in an API job request) if you only need
the speech.

## ffmpeg missing

panoscribe shells out to `ffmpeg` for audio extraction and frame sampling.
If you see an error indicating `ffmpeg` (or `ffprobe`) could not be found:

- **Docker**: not applicable — the image installs `ffmpeg` at build time
  (`Dockerfile:7-9`).
- **Linux**: `apt-get install ffmpeg` (Debian/Ubuntu) or your
  distribution's equivalent.
- **macOS**: `brew install ffmpeg`.
- **Windows**: install from [ffmpeg.org](https://ffmpeg.org/download.html)
  or `winget install ffmpeg`, and ensure the `bin/` directory is on `PATH`.

Verify with `ffmpeg -version` on the same shell/environment panoscribe runs
in.

## Remote speech recognition

These apply only when `PANO_ASR_BACKEND=remote`. See the
[README](../README.md#remote-speech-recognition-opt-in) for setup.

### Model returned no timestamps

Error: `The model '...' returned no segment timestamps`. The remote backend
needs segment timestamps and never invents them. Some servers ignore
`response_format=verbose_json` and return plain text; some models (the
`gpt-4o-transcribe` family) support only plain JSON. Set
`PANO_ASR_REMOTE_MODEL` to a `whisper-1`-style model that returns
`verbose_json` with segments.

### The server rejected the request (HTTP 400)

Error: `rejected the request (HTTP 400) for model '...'`. A common cause is a
model that does not accept `verbose_json` or `timestamp_granularities[]`. Use
a `whisper-1`-style model. Also check that `PANO_ASR_REMOTE_MODEL` names a
model the server actually serves.

### Upload too large (HTTP 413)

Error: `refused the upload as too large (HTTP 413)`. panoscribe splits audio
above `PANO_ASR_REMOTE_MAX_UPLOAD_MB` (default 25), but your server or a proxy
in front of it may allow less. Lower `PANO_ASR_REMOTE_MAX_UPLOAD_MB`. If the
error says the upload limit is too small to split audio, the value is too
small: the smallest usable value is about 0.04 (one second of audio plus
request framing).

### Not found (HTTP 404)

Error: `answered HTTP 404 (model '...')`. The same status comes back for two
different mistakes, so check both. Either `PANO_ASR_REMOTE_MODEL` names a model
the server does not serve, or `PANO_ASR_REMOTE_BASE_URL` is missing the API
version: the base URL must include it, for example
`https://asr.example.com/v1`. panoscribe does not retry a 404.

### Authentication or redirect errors

HTTP 401 or 403 means the key was refused: check `PANO_ASR_REMOTE_API_KEY`. A
3xx reply means the base URL redirects; redirects are never followed so the
key cannot travel to another host. Point `PANO_ASR_REMOTE_BASE_URL` at the
final URL.
