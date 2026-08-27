# Changelog

All notable changes to panoscribe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-08-28

### Added

- **`unmatched_count`/`unmatched_rate` in `src/panoscribe/eval/junk.py`** (#109) — a
  mode-independent replacement for the phase-1 `junk_count`/`junk_rate` metric, now
  the authoritative junk-segment measurement (see "Fixed" below for why). Also added
  `is_unmatched_segment()`, the ground-truth-match check without the duration
  exemption that made phase-1 unreliable.
- **`ExpectedText.appearances`** (`src/panoscribe/eval/models.py`, #109) — optional
  `list[tuple[float, float]]` field recording each on-screen appearance window of a
  required overlay, enabling per-appearance recall instead of a single
  presence/absence check across the whole expected span. `None` preserves the prior
  single-window `[start, end]` behavior.
- **`--platform-profile` on `scripts/eval_ocr.py`** (#109) — the pattern filter was
  previously unreachable for local (non-URL) sources, which is why frequency/pattern
  filtering had measured as "no effect" in 0.4.0; it wasn't ineffective, it was never
  invoked.

### Fixed

- **OCR junk metric reclassified merged multi-frame clusters as non-junk while they
  remained noise** (#109) — the phase-1 `is_junk_segment()` exempted any segment
  lasting >= 1.5s from the junk definition, on the assumption that only fleeting
  single-frame text was noise. Merged clusters of repeated junk across several video
  frames routinely exceeded 1.5s and were counted as legitimate output, and the
  exemption's effect differed between video and images mode. `unmatched_rate`
  (unmatched-to-ground-truth, no duration exemption) replaces it as the authoritative
  metric; `retained_overlay_recall` is now computed per-appearance so partial overlay
  loss within a single required text's lifetime is visible. Corrected baseline on the
  regression fixture (now exercising the video path with lossless determinism, short-
  lived required overlays, stable junk, and UI chrome): **final-stage unmatched rate
  82.6%**, versus the 29% junk rate reported in 0.4.0 — see the correction note under
  0.4.0 below. Findings: `docs/plans/2026-08-27-ocr-noise-measurement.md`.
- **`publish-pypi` job was unreachable and produced a false-green run** (#106) — a job
  whose `needs:` dependency skips is itself skipped regardless of its own `if:`
  condition, and a workflow run where every job is skipped still reports overall
  `success`. Added a `publish-status` job that fails loudly whenever a requested
  publish did not actually happen.
- **`skip-existing` was missing from the TestPyPI publish step** (#107) — re-running
  `publish.yml` after a partial failure re-uploaded the same version to TestPyPI and
  failed on the duplicate. Scoped `skip-existing` to the TestPyPI step only (never
  real PyPI, where a duplicate upload must still fail loudly), making re-runs
  idempotent without weakening the real-PyPI safety check.

### Changed

- **GitHub Release creation automated in `publish.yml`** (#108) — a release is now
  created automatically, gated on a successful real-PyPI publish, with notes sourced
  from the matching `CHANGELOG.md` section. This step existed only as a manual,
  undocumented part of the release process and was missed entirely for the 0.4.0
  release.

### Evaluated, not shipped

- **Low-recurrence OCR filter** (#110) — evaluated against the pre-set 30% relative
  junk-reduction bar and did not clear it: best result was a 19.3% relative cut, and
  the mechanism achieved it by deleting a single-frame *required* overlay while
  removing zero actual junk segments — i.e. it is `dedup_min_duration` under another
  name, the same recall-destroying behavior removed in Sprint OCR-Recall. Not merged.
  Findings: `docs/plans/2026-08-27-ocr-phase2-stability.md`.

## [0.4.0] - 2026-08-27

### Added

- **Trusted-Publishing PyPI release workflow** (`publish.yml`, #100) — OIDC-based
  publish to TestPyPI then PyPI, gated behind a `guard` job that fails the run if the
  pushed tag disagrees with the `pyproject.toml` version literal (no hatch-vcs in this
  repo, so drift is caught mechanically, not prevented structurally), then a `build`
  job (`uv build` + strict `twine check`) and dispatch-gated `publish-pypi`. Also fixes
  two pre-existing packaging defects that would have broken or degraded the first
  upload: the PEP 639 SPDX `license` expression conflicting with the deprecated
  `License :: OSI Approved :: MIT License` classifier (Warehouse rejects distributions
  carrying both — classifier removed), and a missing `src/panoscribe/py.typed` marker
  despite the package declaring `Typing :: Typed` and running `mypy --strict`. See
  `docs/release-process.md` for the exact owner/repo/workflow-filename/environment
  values required in PyPI's and TestPyPI's pending-publisher forms.
- **Real-Whisper end-to-end test** (`tests/test_e2e_whisper.py`, #103), gated behind a
  new `slow` pytest marker — drives a real `WhisperTranscriber` (CPU, `tiny` model)
  over a committed real-speech clip and asserts only on model-nondeterminism-robust
  properties (segment count/timing, non-empty text, detected language, `asr_logprob`
  populated and negative post-#101). Paired with an opt-in `e2e-whisper` CI job
  (nightly `schedule` + `workflow_dispatch`), since the per-PR `test` job is the wrong
  host for a job that downloads model weights.
- **OCR junk-segment measurement harness** (`src/panoscribe/eval/junk.py`, #104) — an
  operational "junk segment" definition (unmatched-to-ground-truth + short duration),
  a deterministic synthetic noise-fixture generator
  (`scripts/generate_ocr_noise_fixture.py`), and a `--junk` flag on `scripts/eval_ocr.py`
  reporting junk metrics at each filter stage. Measurement only — no threshold or
  filter-logic changes in this release. Baseline on the synthetic fixture: 29% of final
  output segments are junk, precision 0.059; pattern/frequency filters show zero effect
  on junk because frequency filtering is structurally one-directional (drops only
  over-frequent text). Findings: `docs/plans/2026-08-27-ocr-noise-measurement.md`.

  > **Correction (0.5.0):** both figures above are known wrong. The 29% junk rate was
  > an artifact of the phase-1 metric's 1.5s duration exemption, which reclassified
  > merged multi-frame junk clusters as non-junk; the corrected, mode-independent
  > measure is 82.6% unmatched. The "zero effect" pattern-filter result was null by
  > construction — `GENERIC_PROFILE` ships an empty `ui_text_patterns`, so no source
  > this baseline used could ever invoke the filter. See `[0.5.0]` below.

### Fixed

- **Fresh-clone bootstrap could not run its own gate** (#98) — `hooks/run-gate.sh` now
  preflight-checks that `pytest_cov` is importable and fails with an actionable message
  instead of pytest's opaque `"unrecognized arguments: --cov=..."` error. Test/dev
  tooling (pytest-cov) is declared in `[project.optional-dependencies]`, not
  `[dependency-groups]`, so a bare `uv sync` (rather than the documented
  `uv sync --extra dev --extra api`) silently skipped it. Docs corrected to match.
- **Stale OmniScribe references in `CHANGELOG.md`** (#99) — the header sentence and all
  release link-reference URLs pointed at `github.com/dagonet/OmniScribe`; GitHub's
  redirect for the renamed repo breaks permanently if the old name is ever reclaimed.
  Updated to `panoscribe`. Dated release entries describing what actually shipped at
  the time (e.g. `src/omniscribe/...` paths, `OMNI_OCR_DET_LANG`) are intentionally
  left untouched.
- **Stale hatchling Metadata-Version comment in `pyproject.toml`** (#102) — the
  `[build-system]` comment claimed `hatchling>=1.27` emits Metadata 2.4; the resolved
  1.32.0 actually emits Metadata-Version 2.5 (verified against the built wheel's
  `dist-info/METADATA`). Corrected to state the actual reason for the version floor
  (PEP 639 support) and note that the emitted Metadata-Version tracks whichever
  hatchling version resolves, rather than being pinned to 2.4.

### Changed

- **`TranscriptSegment.confidence` split into `asr_logprob` and `ocr_confidence`.**
  The old single `confidence` key froze two incompatible scales into one
  user-visible JSON field: ASR wrote a raw, unnormalized Whisper `avg_logprob`
  (roughly `-3.0..0.0`, negative, not a probability), while OCR wrote a
  pixel-match score in `[0.0, 1.0]`. Consumers had no way to tell which scale
  a given segment's `confidence` was on. This is a breaking change to the
  JSON output format (`--format json`), taken deliberately pre-1.0:
  - Old key: `confidence` (meaning depended on `source` — undocumented)
  - New key: `asr_logprob` — populated for `SPEECH`/`BOTH` segments, range
    roughly `-3.0..0.0` (closer to `0` is more confident), `null` otherwise
  - New key: `ocr_confidence` — populated for `ON-SCREEN` segments, range
    `[0.0, 1.0]` (higher is more confident), `null` otherwise
  - A single-source segment never populates both fields; a `[BOTH]` segment
    inherits only `asr_logprob` from its speech side — the two scales are
    still never combined
  Consumers reading `confidence` from JSON output should switch to
  `asr_logprob` or `ocr_confidence` depending on which `source` they care
  about. See `docs/architecture.md` → "JSON output schema — confidence
  fields" for the full table.

- **Project renamed: OmniScribe → panoscribe.** `pip install omniscribe` installs an
  unrelated project (*SoberMind Offline Session Transcriber*), so this project could
  never be published under that name. `panoscribe` was verified free on PyPI, GitHub,
  npm, Docker Hub, and `.com`/`.dev`/`.io` before adoption. This is a breaking change
  for anyone running from source:
  - Package/import: `omniscribe` → `panoscribe` (`src/omniscribe/` → `src/panoscribe/`)
  - CLI command: `omniscribe` → `panoscribe`
  - Environment variable prefix: `OMNI_*` → `PANO_*` (e.g. `OMNI_WHISPER_DEVICE` →
    `PANO_WHISPER_DEVICE`)
  - `pip install panoscribe` replaces `pip install omniscribe`
  See the README "Renamed from OmniScribe" section for the full migration note.

## [0.3.0] - 2026-08-26

### Added

- **`AsrEngine` protocol** (`src/omniscribe/asr/protocol.py`, #90, closes #82) — a `typing.Protocol` + `@runtime_checkable` mirroring the existing `OcrEngine` seam, extracting the interface `WhisperTranscriber` already satisfied. This is a pure refactor with no behavior change; the pipeline still constructs the concrete `WhisperTranscriber` class inline, so the seam does not yet buy anything at runtime on its own — it unblocks #83.
- **Python 3.13 support** — `requires-python` lifted to `>=3.11,<3.14`, a 3.13 classifier added, and CI now runs a 3.11/3.13 matrix. The previous `<3.13` cap and its source comment (claiming `onnxruntime-gpu` 1.24.x published Windows wheels only for cp311/cp312) were both factually wrong: cp313 `win_amd64` wheels have shipped since ORT 1.20.0 and cp314 wheels since 1.24.1, and resolution on 3.13 already succeeded before this change — the cap was simply stale.
- **macOS, Windows ARM, and linux-aarch64 installs now resolve**, selecting the CPU ONNXRuntime build on those platforms (see the `onnxruntime-gpu` marker fix below).
- **`docs/troubleshooting.md`** (#91, closes #80) — covers model download issues, `HF_ENDPOINT` mirrors, `HF_HOME` relocation, offline pre-seeding, CUDA-not-found errors, install failures, and ffmpeg setup.
- **README "Running without a GPU" section** (closes #79) with a measured figure: a 13-second fixture took ~10s wall-clock on CPU with the `small` model, models pre-cached. No GPU comparison was measured for this release, so no speedup ratio is claimed — only the standalone CPU figure.
- **CI `resolve` job** — runs `uv lock --check` plus a `uv pip compile` per platform target, asserting which `onnxruntime` distribution each platform selects, so a future marker regression fails CI instead of surfacing as a silent install-order bug.

### Fixed

- **`onnxruntime-gpu` was an unconditional dependency**, so `pip install` / `uv sync` failed outright on macOS (no macOS wheel exists in any version 1.20–1.29) and on linux-aarch64 below glibc 2.34. It is now marker-gated to `(win32|linux)` × `(x86_64|AMD64)`; every other platform resolves the CPU `onnxruntime` build instead. (#87, closes #78)
- **`faster-whisper` hard-requires plain `onnxruntime<2,>=1.14`, while the project separately declared `onnxruntime-gpu`.** Both distributions installed into the same `onnxruntime/` package directory, so whichever unpacked last silently won — `CUDAExecutionProvider` availability was a matter of install order rather than dependency resolution, and a clean re-sync could have silently dropped CUDA support with no error. A single versioned entry in uv's `override-dependencies` now confines plain `onnxruntime` to the exact complement of the `onnxruntime-gpu` marker, so exactly one distribution is ever selected. Caveat: `override-dependencies` is a uv-only mechanism — a plain `pip install` still pulls both distributions on GPU platforms, which is pre-existing behavior this release does not change.
- **Documented Docker CPU invocation omitted `OMNI_WHISPER_COMPUTE_TYPE`**, leaving the GPU-only `float16` default in place when running on CPU. Fixed in `README.md` and `PROJECT_CONTEXT.md`.

### Changed

- **CUDA-absent failures now fail fast with a clear message.** With `whisper_device`/`ocr_device` left at their `"cuda"` default on a machine with no CUDA device, OmniScribe now raises `OmniScribeError` before model construction, naming the exact remedy, instead of failing deep inside faster-whisper/RapidOCR with an opaque native error. New `src/omniscribe/device.py`. Honest limit: this detects an absent CUDA *runtime* only, not cuDNN sub-library resolution failures, which remain `logger.debug`-only. (#89, closes #81)

## [0.2.6] - 2026-07-16

### Added

- **`ocr_det_lang` detection-language override** (`OMNI_OCR_DET_LANG` = `en` | `ch` | `multi`) — selects the OCR detection model independently of the recognition language, exposing `multi_PP-OCRv3_det_mobile` (the multilingual detector). It was previously unreachable: the engine passed `LangRec` values for `Det.lang_type`, and `LangRec` has no `multi` member — rapidocr resolves detection through a separate `LangDet` enum. `None` default = byte-identical behavior. Added after a Sprint 13 GPU A/B of the `en`/`multi`/`ch-v5` detectors on the eval set found no detector beat the `en_PP-OCRv3_det_mobile` default under the materiality bar; the default is retained and `multi` is an opt-in for hard / low-recall latin-script content (trades ~3–5× raw detections for a small quality edge). Matrix + rationale: `docs/plans/2026-07-16-ocr-det-ab.md`.

## [0.2.5] - 2026-07-15

### Added

- **Eval samples 4-6** — first German-language photo post (sample 5, stylized handwritten-style caps with umlauts) and first animated-text explainer video (sample 6, EN, 8:51). Manifest, fetch entries, and opt-in eval tests with measured baselines.
- **Eval sample 4** — clean multi-paragraph text slides (EN photo post).

### Fixed

- **Unicode-safe slide-image loading** — `RapidOCREngine.extract_images` now uses `np.fromfile` + `cv2.imdecode` via a new `_read_image` helper, supporting filenames with emoji and umlaut characters on Windows. gallery-dl names slides after post captions, which can contain these characters. Previously `cv2.imread` returned `None` silently on such paths (``raw_bboxes=0``, OCR channel empty).
- **Fetch script cross-drive move** — `_download_photo` now uses `shutil.move` instead of `Path.rename`, avoiding ``OSError [WinError 17]`` when system temp and repo are on different drives.
- **Fetch script video target rename** — `_download_video` now captures the return path from `download_video` and moves it to the declared target path, fixing the bug where yt-dlp's `<video-id>.mp4` output was never renamed to `videos/sample-N.mp4`.

## [0.2.4] - 2026-07-14

### Added

- **Eval samples manifest + fetch script** — `tests/fixtures/eval/README.md` documents three eval samples (two TikTok PHOTO posts, one TikTok VIDEO) with source URLs, fixture paths, ground-truth schema, and known-good baselines. `scripts/fetch_eval_samples.py` automates the download (gallery-dl for PHOTO, yt-dlp for VIDEO); idempotent, skips existing files.
- **Opt-in `eval` integration suite** — `tests/test_eval_integration.py` runs the full OCR pipeline against local fixtures and asserts recall >= 1.0 baseline. Gated behind the `eval` pytest marker (excluded from default runs; invoke with `uv run pytest -m eval`). The `pyproject.toml` `addopts` excludes both `integration` and `eval` markers from CI.
- **Unit tests for fetch script** — `tests/test_fetch_eval_samples.py` (5 tests): already-downloaded skip, `--sample` filter, photo-download dir creation, video-download dir creation.

## [0.2.3] - 2026-07-14

### Added

- **Coverage gate enforced in CI at 95%** — `ci.yml` now runs `pytest --cov=omniscribe --cov-report=term-missing --cov-fail-under=95`. The explicit `--cov-fail-under` flag guarantees enforcement even if `pyproject.toml`'s `[tool.coverage.report] fail_under` is not honoured by pytest-cov.
- **Error-path tests** for `audio.py` (ffprobe missing / non-zero exit / empty output / CalledProcessError without stderr), `acquire/photo.py` (`_run_gallery_dl` module + binary fallback paths), `batch.py` (state parse errors, video-ID extraction), and `merge/llm_cleanup.py` (Ollama response-shape guard branches).

### Fixed

- **pytest temp-dir artifact** — `pytest-of-*/` added to `.gitignore` so the temporary factory directory (which was landing in the repo root on this machine) no longer risks accidental tracking.

## [0.2.2] - 2026-07-14

### Added

- **`OcrEngine` protocol** (`omniscribe.ocr.protocol`) — structural `typing.Protocol` describing the OCR backend surface (`extract`, `extract_images`, `last_frame_count`); the extension seam for alternative backends (e.g. the roadmap vision-LLM engine). `RapidOCREngine` conforms.
- **`output.write_transcript(transcript, path, fmt)`** — registry-based output-format dispatcher replacing the CLI-side `match/case`; unknown formats raise `OmniScribeError`.
- **Documentation**: `docs/architecture.md` (module map, pipeline flow, layering rules, extension seams), `docs/configuration.md` (full `OMNI_*` reference with defaults, precedence, validators), `docs/adding-platforms.md` (new-platform guide) — promised by IMPLEMENTATION_PLAN.md's tree since Phase 1, now real. The project-structure tree is synced to reality.

### Changed

- **Internal: pipeline orchestration extracted** from `cli.py` into new `omniscribe.pipeline` module. API server imports from `pipeline` directly, breaking the layering violation where `api/server.py` depended on the CLI module. Test patch seams and CLI call sites now target `omniscribe.pipeline` directly (no re-export shim). `omniscribe.pipeline.process_single_video` is the supported programmatic entry point (optional `console` parameter controls rich output; the API passes none).

## [0.2.1] - 2026-07-14

### Added

- **New `transcribe-many` flags** — `--ocr-language`, `--ui-filter/--no-ui-filter`, and `--scene-change/--no-scene-change` are now available on `transcribe-many`, matching `transcribe` (#52).

### Changed

- **Internal: shared CLI options** — common option definitions are single-sourced via shared `Annotated` type aliases and a unified `_apply_cli_overrides` helper. A parity test (`test_cli_option_parity_between_transcribe_and_transcribe_many`) now fails if the two commands' common option sets drift in name, flag decls, or help text (#52).

### Fixed

- **CI green again / headless Linux imports** — rapidocr hard-depends on the full `opencv-python` wheel, which dlopens `libGL` at import; when GitHub rolled the `ubuntu-latest` runner image on 2026-07-13 (dropping libGL), `import cv2` started failing and every CI run since Sprint 9.6 was red (6 test modules failed collection). A `[tool.uv] override-dependencies` entry now removes `opencv-python` from resolution via an unsatisfiable marker, leaving `opencv-python-headless` (API-identical for rapidocr's usage) as the only `cv2` provider. Note for existing local venvs: run `uv sync` and, if `import cv2` then fails, `uv pip install --reinstall opencv-python-headless` once — uninstalling the full wheel can orphan the shared `cv2/` files.

## [0.2.0] - 2026-07-13

### Added

- **HTTP API mode** (#55) — new `omniscribe serve` command starts a FastAPI server with `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, and `GET /healthz` endpoints. Requires the `[api]` extra: `uv sync --extra api`. Single-worker executor with per-job temp directories. v1 limitations documented in README (no auth, no persistence, shutdown-hang).

## [0.1.9] - 2026-07-13

### Added

- **Speech translation** — new `--translate/--no-translate` CLI flag (both `transcribe` and `transcribe-many`) and `OMNI_WHISPER_TASK` env var expose Whisper's native `task=translate`: speech from any supported source language is transcribed directly into English. On-screen text (OCR) intentionally stays in the source language, so translated runs emit `[SPEECH]` (English) + `[ON-SCREEN]` (source) without cross-language `[BOTH]` merges. Speech segment `language` fields report `en` under translate; the top-level transcript language remains the detected source language.

## [0.1.8] - 2026-07-13

### Fixed

- **Docker image now bundles the `[photo]` extra** (gallery-dl): TikTok `/photo/` post URLs previously failed in-container because gallery-dl was not installed. Both `uv sync` layers in the Dockerfile now pass `--extra photo`. README Docker section documents the bundled extras (and that `[llm]` intentionally stays out — Ollama is host-external).

## [0.1.7] - 2026-07-13

### Added

- **Photo-mode-native pipeline** (#46): native processing of TikTok `/photo/` posts — slides + audio are downloaded via gallery-dl (new `[photo]` extra), OCR'd at native resolution (extract_images), and spread across audio duration for timestamped output. `omniscribe transcribe <TikTok-photo-URL>` and `omniscribe transcribe <local-dir>` both work. `scripts/eval_ocr.py --images DIR` for evaluation. GPU-verified: sample-1 native recall **1.0** vs 0.25 stitched (raw det boxes 320 vs 136). Closes #46.

### Fixed

- **Position-aware intra-frame dedup** (#40): `aggregate_frame_bboxes` now checks spatial overlap (axis-aligned intersection on both axes) instead of frame-wide text-only matching when deduplicating same-text detections. Same text in different columns or rows is no longer silently dropped; overlapping double-detections (RapidOCR's most common duplicate pattern) are still deduped correctly. Closes #40.

## [0.1.6] - 2026-07-13

### Added

- **RapidOCR det knobs** (#41): three optional env overrides — `OMNI_OCR_DET_LIMIT_SIDE_LEN`, `OMNI_OCR_DET_THRESH`, `OMNI_OCR_DET_BOX_THRESH` — expose RapidOCR's `Det.*` params for the #41 grid search on dense-small-text content. Defaults are None (zero behavior change) until data-driven values are chosen.
- **RapidOCR model-variant knobs** (#41 phase 2): four optional env overrides — `OMNI_OCR_DET_MODEL_TYPE`, `OMNI_OCR_DET_OCR_VERSION`, `OMNI_OCR_REC_MODEL_TYPE`, `OMNI_OCR_REC_OCR_VERSION` — expose RapidOCR's higher-capacity model variants (server / PP-OCRv5) for the #41 GPU capability probe. Defaults are None (rapidocr default: mobile / PP-OCRv4). **CH-det-lang auto-override**: when det model type is `server` or det OCR version is `PP-OCRv5`, the det language parameter is forced to `CH` because rapidocr's model registry ships det models only as `ch_*` for those variants. Part of #41.

### Notes

- #41 grid verdict: all det variants (v3/v4/v5, mobile/server) plateau on the stitched photo-post fixture; the default mobile det reads native slide images fine (56 vs ~17 boxes/slide). Bottleneck is the stitched-video representation of photo-mode posts — addressed by the photo-mode-native pipeline (next). Knobs remain as diagnostics.

## [0.1.5] - 2026-07-13

### Fixed

- **Column-aware line splitting (`aggregate_frame_bboxes`)** (#39): aggregator now retains x-extents and splits same-y-line boxes at gaps > 2.0x frame-wide mean box height; word gaps stay joined, column gutters split. New ``x_gap_tolerance_ratio`` parameter (default ``2.0``). GPU-measured: split granularity confirmed (85 → 132 segments on the infographic sample); that sample's recall remains detection-limited — small dense text never reaches OCR output (tracked in #41).
- **Greedy triple eval matching** (#39): 3-line GT texts now matchable via greedy extend-best-pair; gated to run only when singles+pairs fall below threshold. New ``_best_triple_extension`` helper. GPU-verified: sample-2 recall 0.833 → 1.0; sample-3 unchanged at 1.0.

## [0.1.4] - 2026-07-12

### Fixed

- **Multi-line eval matching**: GT texts spanning multiple visual lines now match when OCR emits per-line segments; scoring tries pairwise concatenation (both orders) of segments within a 2.0 s start-span window; precision counts pair participants via union with the existing per-segment semantics. Verified on GPU: sample-3 recall 0.5 → 1.0, precision 0.333 → 0.667.
- **Frequency-filter min-frame guard**: new ``ocr_frequency_min_frame_count`` config (default 10, env ``OMNI_OCR_FREQUENCY_MIN_FRAME_COUNT``); ``filter_by_frequency`` skips filtering below the minimum so ≤9-frame clips (photo slideshows) no longer lose all text.

## [0.1.3] - 2026-07-12

### Changed

- **`ocr_language` default flipped from `"en"` to `"auto"`** (#33). OCR now resolves the recognition language at runtime using the ASR-detected language. Falls back to EN when detection is unavailable or unmapped. Latin rec model preserves umlauts/accents on German/French/Spanish/etc. content.

### Added

- **ISO-639 language mapping** (#32). 50+ ISO 639-1 codes mapped to PP-OCRv4 recognition models. Latin-script languages (de/fr/es/…) → `latin` rec model; Cyrillic → `cyrillic`, Slavic → `eslav`, CJK → `ch`/`japan`/`korean`. Config field_validator accepts `"auto"`, all LangRec values, and mapped ISO codes; rejects unknown values at construction.
- **Toggleable auto-caption mask** (#32). New `ocr_mask_auto_captions` config flag (default `true`, env `OMNI_OCR_MASK_AUTO_CAPTIONS`). Caption-band zones moved from `ui_exclusion_zones` to `auto_caption_zones` on TikTok/Instagram profiles — mask them independently of UI exclusion zones.
- **CLI wiring**: `detected_language` from ASR passed to OCR engine for runtime language resolution (#32).

## [0.1.2] - 2026-07-12

### Added

- **Docker containerization** (Phase 5). Single-stage `nvidia/cuda:12.6.3-runtime-ubuntu22.04` image with Whisper `large-v3-turbo` and RapidOCR models pre-downloaded. GPU passthrough via NVIDIA Container Toolkit; CPU fallback via `OMNI_WHISPER_DEVICE=cpu`. Added missing `opencv-python-headless` dependency.
- **Playlist / channel auto-expansion in `transcribe-many`** (Sprint 8.1). Lines in the URL list that resolve to a playlist or channel are automatically expanded via yt-dlp's `extract_flat`, in feed order, before per-video processing. Mix freely with single-video URLs and local file paths in the same `urls.txt`. Sequential expansion + processing; no caching across runs (yt-dlp's `extract_flat` is metadata-only and cheap).

### Changed

- Internal: `cli.transcribe()`'s orchestration body extracted into a module-level `process_single_video()` helper so the batch command can reuse it. No behavior change for the single-video path.
- **`transcribe-many` URL list semantics** (Sprint 8.1). Lines that yt-dlp resolves to a playlist URL now auto-expand inline. Previously such lines failed at the per-video extractor with an opaque error. Existing `urls.txt` files containing single-video URLs and local file paths are unaffected.

## [0.1.1] - 2026-04-30

### Fixed

- **Windows GPU now works without a system CUDA install** (Sprints 7.2–7.4, PRs #22–#24). `nvidia-cuda-runtime-cu12`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, and `nvidia-cufft-cu12` are now bundled on Windows via pip (gated `sys_platform == 'win32'`). A new module-import shim in `src/omniscribe/asr/whisper.py` registers each `nvidia/*/bin` directory and ctypes-preloads `cudart64_12.dll → cublas64_12.dll → cudnn64_9.dll + all cuDNN sub-libraries (glob "cudnn_*.dll") → cufft64_11.dll`, so both faster-whisper / CTranslate2 and onnxruntime-gpu's `CUDAExecutionProvider` (used by RapidOCR) find their dependencies at inference time. Smoke-validated end-to-end on a 41-min video at ~2.7× realtime.
- **Inclusive merge boundary for `[BOTH]` segments** (`681fa03`). `merge_channels` previously used strict `<` overlap; the loosened `≤` boundary correctly emits a single `[BOTH]` segment when speech and OCR end at the same timestamp.
- **LLM cleanup robustness** (`681fa03`). Added a model pre-warm step, carriage-return stripping in cleaned output, and configurable `keep_alive` for the Ollama client.
- **typer dep cleanup** (`0e2ab46`, PR #19). Replaced the deprecated `typer[all]` extra with `typer>=0.13`, which now bundles `rich` and `shellingham` as direct deps.

### Added

- **Caption-region masking + fuzzy frequency filter** (Sprint 7.1, PR #20). New `src/omniscribe/ocr/_text_match.py` module with `_canonical_key` / `_fuzzy_match` primitives shared between the cross-frame deduplicator and UI filter. Platform profiles for TikTok and Instagram now carry `RelativeRect` caption-band coordinates so OCR-side noise (rolling auto-captions, recurring SUBSCRIBE prompts) gets zeroed before detection. Default `fuzzy_threshold=90` (rapidfuzz `WRatio`).

### Changed

- **DeepWiki badge added to README** (`d9a98e6`).
- **Template sync** (`898ed1b`). Pulled upstream agent / settings / CLAUDE.md updates from the `claude-code-toolkit` template (`f229832 → 788902d`). No user-facing behavior change.

## [0.1.0] - 2026-04-25

First public alpha. Core pipeline ships: video acquisition (yt-dlp) →
audio extraction (ffmpeg) → ASR (faster-whisper large-v3-turbo) +
OCR (RapidOCR) → cross-frame OCR dedup → cross-source merge →
multi-format output (JSON / TXT / SRT / Markdown).

### Added

#### Phase 1 — Foundation + ASR
- Project skeleton (`pyproject.toml`, ruff, mypy, pytest) targeting Python 3.11/3.12.
- Configuration via pydantic-settings with `OMNI_*` environment-variable namespace.
- Video acquisition pipeline using yt-dlp; audio extraction via ffmpeg.
- ASR using `faster-whisper large-v3-turbo` on CUDA (CPU fallback).
- Output writers for JSON, TXT, SRT, and Markdown.

#### Phase 2 — OCR
- RapidOCR engine wrapper with CUDA / CPU device selection.
- Frame sampler with scene-change detection (Sprint 2.5; PR #3).
- Per-frame bbox aggregation: same-y-line bboxes joined into canonical
  caption strings before dedup (Sprint OCR Recall Part 1; PR #16).
- Cross-frame deduplicator clustering same-text overlays held across
  multiple sampled frames. Refactored to text-grouped clustering so
  multi-region-per-frame layouts collapse correctly (Sprint OCR Recall
  Part 2; PR #17).

#### Phase 3 — Platform profiles
- Profile system for TikTok, YouTube (incl. Shorts), Instagram Reels.
- UI text filtering (regex patterns + frequency-based) to drop platform
  chrome (`@username`, like counts, "Original Sound by …", channel pills).

#### Phase 4 — Merge engine
- `merge_channels` collapses temporally-overlapping SPEECH and OCR
  segments with WRatio similarity ≥ 0.85 into single `[BOTH]` segments;
  unmatched OCR is preserved as `[ON-SCREEN]`.
- Case-insensitive comparison via `processor=str.lower` (Sprint OCR Recall
  Part 1 risk-2 fix).

#### Phase 5 — Trust + CI
- Sprint 5.1: docs-only trust-repair pass after Phase 5 audit.
- Sprint 5.2: GitHub Actions CI (ruff format, ruff check, pytest) on push
  and PR; status badge in README.

#### Phase 6 — LLM cleanup (opt-in)
- Sprint 6.1 (PR #12): LLM cleanup infrastructure plus on-screen text
  artifact-fix prompt; opt-in via `--llm-cleanup` and `[llm]` extras.
  Requires a local Ollama server.
- Sprint 6.2 (PR #14): LLM punctuation cleanup on speech segments;
  opt-in via `--asr-cleanup`.

### Configuration
- `dedup_min_duration` defaults to `0.0` post-aggregation. Validator
  rejects negative values.
- `merge_similarity_threshold` defaults to `0.85`.
- `dedup_similarity_threshold` defaults to `0.85`.
- All `OMNI_*` env vars documented in `src/omniscribe/config.py`.

### Test suite
- 296 unit and integration tests covering ASR, OCR, dedup, UI filter,
  platform profiles, merge, output formats, LLM cleanup, and CLI plumbing.

### Known limitations
See README "Known Limitations" — OCR noise on text-heavy backgrounds and
strict-`<` boundary in `[BOTH]` emission are the two areas tracked for
post-0.1.0 work.

[0.5.0]: https://github.com/dagonet/panoscribe/releases/tag/v0.5.0
[0.4.0]: https://github.com/dagonet/panoscribe/releases/tag/v0.4.0
[0.2.5]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.5
[0.2.4]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.4
[0.2.3]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.3
[0.2.2]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.2
[0.2.1]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.1
[0.2.0]: https://github.com/dagonet/panoscribe/releases/tag/v0.2.0
[0.1.9]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.9
[0.1.8]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.8
[0.1.7]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.7
[0.1.6]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.6
[0.1.5]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.5
[0.1.4]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.4
[0.1.3]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.3
[0.1.2]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.2
[0.1.1]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.1
[0.1.0]: https://github.com/dagonet/panoscribe/releases/tag/v0.1.0
