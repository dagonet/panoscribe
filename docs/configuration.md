# Configuration Reference

panoscribe is configured via environment variables, a `.env` file, or CLI flags.
All configuration is validated at startup by `PanoScribeConfig` (a
`pydantic-settings` `BaseSettings`).

## Loading order

1. `PanoScribeConfig()` is constructed at CLI startup in the `main` callback.
2. `pydantic-settings` reads `PANO_`-prefixed environment variables, then falls
   back to a `.env` file in the current working directory.
3. CLI flags override config values via `_apply_cli_overrides()` in `cli.py`,
   which creates a `model_copy(update=...)` with the non-None flag values.

### Output format resolution

Output format is resolved separately in `pipeline._resolve_output_format()` with
its own precedence chain:

1. `--format` CLI flag (highest)
2. `PANO_OUTPUT_FORMAT` env var (if set — presence triggers this branch)
3. Output-path extension (`.json` / `.txt` / `.srt` / `.md`)
4. Hard default `"json"`

## Field table

### ASR

See [Running without a GPU](../README.md#running-without-a-gpu) for the
CPU env-var combination (`whisper_device` + `whisper_compute_type`).

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `whisper_model` | `PANO_WHISPER_MODEL` | `"large-v3-turbo"` | Faster-Whisper model size or path |
| `whisper_device` | `PANO_WHISPER_DEVICE` | `"cuda"` | Torch device for Whisper inference |
| `whisper_compute_type` | `PANO_WHISPER_COMPUTE_TYPE` | `"float16"` | Compute precision (`"float16"`, `"float32"`, `"int8_float16"`, etc.) |
| `whisper_batch_size` | `PANO_WHISPER_BATCH_SIZE` | `16` | Batched inference batch size |
| `whisper_language` | `PANO_WHISPER_LANGUAGE` | `None` | Force ASR language (e.g. `"en"`); `None` = auto-detect |
| `whisper_task` | `PANO_WHISPER_TASK` | `"transcribe"` | `"transcribe"` or `"translate"` (translate speech to English) |

### Remote ASR

Opt-in: speech recognition runs locally unless `PANO_ASR_BACKEND=remote`.
**When it is remote, your audio leaves the machine.** Setting the backend to
`remote` together with a base URL and a model is the whole opt-in; the
`remote-asr` extra (`uv sync --extra remote-asr`) is only the supported way to
install `httpx`. These fields come from the environment or `.env` only: there
are no CLI flags and the HTTP API cannot set them per job. `whisper_model`,
`whisper_device`, `whisper_compute_type` and `whisper_batch_size` are ignored
when remote; `whisper_language` is honoured and sent as `language`.
`whisper_task="translate"` is refused with the remote backend. OCR always stays
local. Environment proxy and TLS settings (`HTTP_PROXY`, `HTTPS_PROXY`,
`ALL_PROXY`, `SSL_CERT_FILE`, `SSL_CERT_DIR`) are honoured, except for a
loopback server (`localhost`, `127.0.0.1`, `::1`): it is always reached
directly and ignores `SSL_CERT_FILE` and `SSL_CERT_DIR` too, so
`https://localhost` with a private CA is not supported. Do not put credentials anywhere in the base
URL: user-info, a query string and a fragment are refused, and a token in the
path cannot be recognised and kept out of logs or proxies. See the [README](../README.md#remote-speech-recognition-opt-in).

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `asr_backend` | `PANO_ASR_BACKEND` | `"local"` | `"local"` or `"remote"` |
| `asr_remote_base_url` | `PANO_ASR_REMOTE_BASE_URL` | `None` | Base URL including the version, e.g. `https://host/v1`. Required when remote. No vendor default |
| `asr_remote_model` | `PANO_ASR_REMOTE_MODEL` | `None` | Model name. Required when remote. Must return `verbose_json` with segment timestamps (`whisper-1` style). No vendor default |
| `asr_remote_api_key` | `PANO_ASR_REMOTE_API_KEY` | `None` | Bearer token, held as a secret and never logged. Optional: self-hosted servers often need none |
| `asr_remote_timeout_s` | `PANO_ASR_REMOTE_TIMEOUT_S` | `600.0` | Timeout in seconds for the read, write and pool phases of a request (must be finite and > 0). The connect timeout is fixed at 10 s |
| `asr_remote_max_retries` | `PANO_ASR_REMOTE_MAX_RETRIES` | `3` | Retries after a 429, 500, 502, 503 or 504 status, a timeout or a connection error (must be >= 0) |
| `asr_remote_max_upload_mb` | `PANO_ASR_REMOTE_MAX_UPLOAD_MB` | `25.0` | Request size above which audio is split (must be finite, > 0 and at most 1,000,000). Here 1 MB means 1,000,000 bytes, and 4 KiB is held back for the request framing, so a chunk plus its framing stays inside the limit |

### OCR

See [Running without a GPU](../README.md#running-without-a-gpu) for setting
`ocr_device` to `"cpu"`.

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `ocr_enabled` | `PANO_OCR_ENABLED` | `True` | Master switch for the OCR pipeline |
| `ocr_language` | `PANO_OCR_LANGUAGE` | `"auto"` | RapidOCR `LangRec` value, `"auto"` (resolve from ASR language), or ISO 639-1 code |
| `ocr_mask_auto_captions` | `PANO_OCR_MASK_AUTO_CAPTIONS` | `True` | When `True`, the auto-caption zone from the platform profile is masked (excluded from OCR) |
| `ocr_sample_fps` | `PANO_OCR_SAMPLE_FPS` | `1.0` | Frame sampling rate (frames per second of video) |
| `ocr_min_confidence` | `PANO_OCR_MIN_CONFIDENCE` | `0.6` | Minimum OCR confidence score (0.0–1.0) for a detection to be kept |
| `ocr_device` | `PANO_OCR_DEVICE` | `"cuda"` | ONNX Runtime device for RapidOCR (`"cuda"` or `"cpu"`) |
| `scene_change_enabled` | `PANO_SCENE_CHANGE_ENABLED` | `True` | Enable scene-change detection in the frame sampler |
| `scene_change_threshold` | `PANO_SCENE_CHANGE_THRESHOLD` | `0.02` | Normalised mean-absdiff threshold for scene-change detection (0.0–1.0) |
| `ocr_frequency_min_frame_count` | `PANO_OCR_FREQUENCY_MIN_FRAME_COUNT` | `10` | Minimum frame count for the frequency filter to activate (guard for short clips) |
| `ocr_det_limit_side_len` | `PANO_OCR_DET_LIMIT_SIDE_LEN` | `None` | RapidOCR Det limit_side_len override (≥ 32, or `None` for config default) |
| `ocr_det_thresh` | `PANO_OCR_DET_THRESH` | `None` | RapidOCR Det detection threshold (0.0–1.0, or `None` for default) |
| `ocr_det_box_thresh` | `PANO_OCR_DET_BOX_THRESH` | `None` | RapidOCR Det box threshold (0.0–1.0, or `None` for default) |
| `ocr_model_set` | `PANO_OCR_MODEL_SET` | `"classic"` | Which OCR models run: `"classic"` (rapidocr's PP-OCRv4 mobile route; PP-OCRv5 recognition for Eastern Slavic, Thai and Greek) or `"v6"` (PP-OCRv6 small, with a per-language fallback to classic). Empty means `"classic"`. The default was decided by measurement, see [the report](plans/2026-11-08-ocr-v6-measurement.md) |
| `ocr_det_lang` | `PANO_OCR_DET_LANG` | `None` | Detection model language (`"en"`, `"ch"` or `"multi"`). `None` = chosen from the OCR language. An empty `PANO_OCR_DET_LANG=` is rejected (unlike the four model-type and version fields, it is not read as unset). Under the `v6` set it keeps detection on the classic model; with `ocr_det_ocr_version="pp-ocrv6"` only `"en"` and `"ch"` are valid |
| `ocr_det_model_type` | `PANO_OCR_DET_MODEL_TYPE` | `None` | Detection model variant: `"mobile"` or `"server"` (PP-OCRv4, PP-OCRv5); `"tiny"`, `"small"` or `"medium"` (PP-OCRv6). `None` = the model set decides |
| `ocr_det_ocr_version` | `PANO_OCR_DET_OCR_VERSION` | `None` | Detection OCR version (`"pp-ocrv4"`, `"pp-ocrv5"` or `"pp-ocrv6"`). `None` = the model set decides |
| `ocr_rec_model_type` | `PANO_OCR_REC_MODEL_TYPE` | `None` | Recognition model variant: `"mobile"` or `"server"` (PP-OCRv4, PP-OCRv5); `"tiny"`, `"small"` or `"medium"` (PP-OCRv6). `None` = the model set decides |
| `ocr_rec_ocr_version` | `PANO_OCR_REC_OCR_VERSION` | `None` | Recognition OCR version (`"pp-ocrv4"`, `"pp-ocrv5"` or `"pp-ocrv6"`). `None` = the model set decides |

A model-type or version setting that does not fit the version in effect for the task (for example `medium` with PP-OCRv4, or PP-OCRv6 for a language that has no v6 model) stops the run with an error naming the setting or the language, and what is allowed. The error comes before any download when it is wrong whatever the language is, or when `PANO_OCR_LANGUAGE` is set (not `auto`); with `auto`, a problem that depends on the detected language stops OCR for that item when the OCR engine starts (after the download and speech recognition). `--no-ocr` skips the check. See [Troubleshooting](troubleshooting.md#ocr-fails-to-start-with-an-explicit-model-setting).

### LLM cleanup

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `llm_cleanup_enabled` | `PANO_LLM_CLEANUP_ENABLED` | `False` | Enable Ollama-backed OCR artefact cleanup on ON-SCREEN and BOTH segments |
| `llm_cleanup_model` | `PANO_LLM_CLEANUP_MODEL` | `"llama3.2:3b"` | Ollama model name for cleanup |
| `llm_cleanup_host` | `PANO_LLM_CLEANUP_HOST` | `"http://localhost:11434"` | Ollama server URL |
| `llm_cleanup_timeout_s` | `PANO_LLM_CLEANUP_TIMEOUT_S` | `30.0` | HTTP request timeout for Ollama calls (must be > 0) |
| `llm_cleanup_keep_alive_s` | `PANO_LLM_CLEANUP_KEEP_ALIVE_S` | `300.0` | Ollama model keep-alive duration after last call (≥ -1.0; -1 = forever) |
| `llm_asr_cleanup_enabled` | `PANO_LLM_ASR_CLEANUP_ENABLED` | `False` | Enable Ollama-backed punctuation + capitalisation cleanup on SPEECH segments |

### Platform

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `platform_profile` | `PANO_PLATFORM_PROFILE` | `"auto"` | Platform profile name (`"auto"`, `"tiktok"`, `"youtube"`, `"instagram"`, `"generic"`) |
| `ui_filter_enabled` | `PANO_UI_FILTER_ENABLED` | `True` | Enable zone masking, pattern filtering, and frequency filtering |

### Dedup

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `dedup_similarity_threshold` | `PANO_DEDUP_SIMILARITY_THRESHOLD` | `0.85` | RapidFuzz `WRatio` threshold (0.0–1.0) for same-source OCR dedup |
| `dedup_min_duration` | `PANO_DEDUP_MIN_DURATION` | `0.0` | Minimum duration in seconds for a dedup cluster span (≥ 0.0) |

### Merge

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `merge_similarity_threshold` | `PANO_MERGE_SIMILARITY_THRESHOLD` | `0.85` | RapidFuzz `WRatio` threshold (0.0–1.0) for cross-source SPEECH+OCR merge |

### Output

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `output_format` | `PANO_OUTPUT_FORMAT` | `"json"` | Default output format (`"json"`, `"txt"`, `"srt"`, `"md"`) |

### General

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `temp_dir` | `PANO_TEMP_DIR` | `{tempdir}/panoscribe` | Working directory for downloads and intermediate files |
| `keep_temp_files` | `PANO_KEEP_TEMP_FILES` | `False` | If `True`, temp files are not cleaned up after processing |
| `log_level` | `PANO_LOG_LEVEL` | `"INFO"` | Logging level (`"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`) |

## Config naming convention

Every field maps to `PANO_` + the uppercased field name. For example,
`ocr_sample_fps` becomes `PANO_OCR_SAMPLE_FPS`. Nested or composed field names
use underscores in the env var as they do in the Python field name.

## CLI override mechanism

Boolean flags (`--ocr/--no-ocr`, `--ui-filter/--no-ui-filter`,
`--scene-change/--no-scene-change`, `--llm-cleanup/--no-llm-cleanup`,
`--asr-cleanup/--no-asr-cleanup`, `--translate/--no-translate`) set or clear
the corresponding config field when explicitly passed. String options
(`--language`, `--ocr-language`, `--platform`) override the matching field.
`--ocr` is handled separately as a pipeline parameter rather than a config field
override.

## Validation rules

| Field(s) | Rule | Error condition |
|---|---|---|
| `whisper_language`, `ocr_det_limit_side_len`, `ocr_det_thresh`, `ocr_det_box_thresh`, `ocr_det_model_type`, `ocr_det_ocr_version`, `ocr_rec_model_type`, `ocr_rec_ocr_version` | Coerces empty-string env values to `None` | — (empty string treated as unset) |
| `ocr_model_set` | Must be `classic` or `v6` (case-insensitive); an empty value means `classic` | Unknown value rejected with list of allowed options |
| `asr_backend` | Must be `local` or `remote` | Unknown value rejected |
| `asr_remote_base_url`, `asr_remote_model`, `asr_remote_api_key` | Surrounding whitespace is stripped; blank becomes `None` | — (a pasted key with a trailing newline is accepted) |
| `asr_remote_timeout_s`, `asr_remote_max_upload_mb` | Must be finite and `> 0`; the upload limit is at most 1,000,000 | Zero, negative, `nan`, `inf` and (for the limit) larger values rejected |
| `asr_remote_max_retries` | Must be `>= 0` | Negative values rejected |
| Remote URL and key content | Checked when the remote engine is built, not at config load, because a validation error prints its input. The URL must be `http` or `https` with a host and no user-info, query string or fragment; the key must be printable ASCII with no whitespace | The engine refuses with an error that does not echo the value |
| `platform_profile` | Must be one of `auto`, `tiktok`, `youtube`, `instagram`, `unknown`, `generic` | Unknown value rejected with list of allowed options |
| `scene_change_threshold` | Must be in `(0.0, 1.0]` | `0.0` (defeats feature) or `> 1.0` (impossible) rejected |
| `llm_cleanup_timeout_s` | Must be `> 0` | Zero or negative values rejected |
| `llm_cleanup_keep_alive_s` | Must be `≥ -1.0` | Values below `-1.0` rejected |
| `output_format` | Must be one of `json`, `txt`, `srt`, `md` | Unknown value rejected with list of allowed options |
| `dedup_min_duration` | Must be `≥ 0.0` | Negative values rejected |
| `ocr_language` | Must be a valid `LangRec` member, `"auto"`, or a mapped ISO 639-1 code | Unmapped arbitrary strings rejected before engine init |
| `ocr_det_model_type`, `ocr_rec_model_type` | Must be `"mobile"`, `"server"`, `"tiny"`, `"small"` or `"medium"` (case-insensitive), or `None` | Unknown values rejected. A value that does not fit the version in effect (`tiny`/`small`/`medium` are PP-OCRv6 only; `mobile`/`server` are PP-OCRv4 and PP-OCRv5 only) is rejected before any download when OCR is on, unless the answer depends on the detected language (`ocr_language=auto` with the `v6` set), in which case it is rejected when the OCR engine starts |
| `ocr_det_ocr_version`, `ocr_rec_ocr_version` | Must be `"pp-ocrv4"`, `"pp-ocrv5"` or `"pp-ocrv6"` (case-insensitive), or `None` | Unknown values rejected |
| `ocr_det_lang` | Must be `"en"`, `"ch"` or `"multi"` (case-insensitive), or `None` | Unknown values rejected. With a PP-OCRv6 detector pinned by `ocr_det_ocr_version`, `"multi"` is rejected before any download when OCR is on |
| `merge_similarity_threshold` | Must be in `[0.0, 1.0]` | Out-of-range values rejected |
