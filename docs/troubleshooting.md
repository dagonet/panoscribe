# Troubleshooting

## Model downloads on first run

panoscribe does not bundle models outside the Docker image. On first run
(non-container installs), the two backends pull their weights from
Hugging Face Hub automatically:

- **faster-whisper** downloads the configured `PANO_WHISPER_MODEL`
  (default `large-v3-turbo`) — roughly **1.6 GB**.
- **RapidOCR** downloads its detection/recognition models — roughly
  **15 MB**.

Both are cached after the first run, so subsequent runs do not re-download.
The Docker image (`Dockerfile:27-31`) pre-downloads both at build time, so
containerized runs never hit the network for models.

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

Set `HF_HOME` before the first run so both the Whisper and RapidOCR
downloads land in the same place.

### Offline pre-seeding

To avoid a network dependency at run time (air-gapped environments, CI),
pre-download both models once with `HF_HOME` (or the default cache) set to
a location you control, then copy that cache to the target machine:

```bash
# On a machine with network access:
HF_HOME=./model-cache python -c \
  "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"
HF_HOME=./model-cache python -c \
  "from rapidocr import RapidOCR; RapidOCR(params={'EngineConfig.onnxruntime.use_cuda': False})"

# Copy ./model-cache to the target machine, then:
export HF_HOME=/path/to/model-cache
```

This is the same technique the Dockerfile uses at build time.

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
