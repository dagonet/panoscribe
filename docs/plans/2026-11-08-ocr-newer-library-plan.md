# Newer OCR Library Support (v0.10.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run panoscribe on rapidocr 3.10 for every mapped language with two model sets (`classic`, `v6`). Measure `v6` against `classic` on real clips to decide the default. Add an unmocked engine check to CI. Ship #183 and #184 in the same release.

**Architecture:**
- A new pure module, `ocr/model_sets.py`, turns config + resolved language into the rapidocr language/version/model-type params. `RapidOCREngine._ensure_loaded` uses it, so every rule is unit-testable without the engine.
- A reusable probe (`scripts/probe_ocr_languages.py`) starts the real engine per language. It records the 3.8.1 baseline and backs the new CI job.
- The measurement reuses `scripts/eval_ocr.py`, plus a small summariser that pools results per language.

**Tech Stack:** Python 3.11/3.13, rapidocr 3.10 (onnxruntime), pydantic-settings, typer + rich, pytest, GitHub Actions, uv.

**Spec:** `docs/plans/2026-11-08-ocr-newer-library-design.md` (approved 2026-11-08). Read it first; D-numbers below refer to it.

## Global Constraints

- **rapidocr range:** `rapidocr>=3.10,<3.11` in `pyproject.toml`; `uv.lock` at rapidocr 3.10.0 (D1).
- **Model-set setting:** `PANO_OCR_MODEL_SET` = `classic` | `v6`. The default is `classic` until Task 9 decides otherwise (D2, D5).
- **`classic`** = Det and Rec `PP-OCRv4` + `mobile`, with today's language values. Rec uses `PP-OCRv5` + `mobile` for `eslav`, `th` and `el` (D3a).
- **`v6`** = Det and Rec `PP-OCRv6` + `small`, with the language's v6 code. Without a v6 code, the whole language falls back to `classic`, with one INFO log line (D3).
- **Explicit knobs win and are never silently changed.** `PANO_OCR_{DET,REC}_{OCR_VERSION,MODEL_TYPE}` and `PANO_OCR_DET_LANG` keep overriding. The language value is chosen by the *effective* version; an unroutable explicit combination fails with `PanoScribeError` (D3b, D4).
- **Library defaults stay untouched:** do not set `Global.use_preprocess_img`, `Global.use_vertical_padding` or any Cls key.
- **Pipeline stages stay untouched:** no change to filters, dedup, merge or LLM cleanup.
- **Third-party material stays out of git.** Clips and answer keys are never committed; they live only in the gitignored `tests/fixtures/eval/{videos,slides}/` and `gt-*.json`.
- **User-facing errors:** plain words, `str(e)` only, never an exception chain or a secret.
- **Decision rule (D5).** Per language EN/DE/FR/ES/PT, pooled over that language's clips:
  - `recall_v6 >= recall_classic - 0.02`;
  - `unmatched_rate_v6 <= unmatched_rate_classic + 0.02`;
  - and overall pooled recall_v6 >= recall_classic.
- **CI:** `test` (coverage `--cov-fail-under=95`) and `resolve` stay green. The new engine job is required on every PR.
- **Commits and PRs.** One commit per task, grouped into three PRs to keep the maintainer's merges few:
  - **PR A** = Tasks 1–2;
  - **PR B** = Tasks 3–7, in order, so the 3.8.1 baseline is recorded before the bump;
  - **PR C** = Tasks 9–10.

  Task 8 commits nothing.
  - Run `git add <explicit paths>` in its own call, then `git commit -F <file>`.
  - Every commit message ends with the two lines `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_019z1Ri2ayirzjPuRv1FKM9E`.
  - Every PR body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, a blank line, then `https://claude.ai/code/session_019z1Ri2ayirzjPuRv1FKM9E`.
  - Agents never merge; the maintainer does.

## Review Focus

1. **`ocr_language="latin"` set explicitly, with `PANO_OCR_MODEL_SET=v6`:** falls back to `classic` and starts. It must not error, because `latin` has no v6 code. Test: Task 5.
2. **`ocr_language="auto"` with a detected code that is unmapped (`"xx"`) or `None`, under `v6`:** resolves to `en` on the v6 path and starts. Test: Task 5.
3. **A failure message containing square brackets** (`[Errno 2] ...`, `"[On] ..."`) in the #184 line: printed literally, not eaten as rich markup and not crashing. Test: Task 1.
4. **A TikTok photo post without audio while the remote speech settings are wrong:** fails early with the settings message. The settings are wrong, and the next video would fail anyway. Test: Task 2.
5. **`PANO_OCR_REC_OCR_VERSION=PP-OCRv6` with no model-type knob:** model type defaults to `small` (not rapidocr's mobile/server), and `de` passes its ISO code. Test: Task 5.

---

### Task 1: #184 — `transcribe-many` prints why an item failed

**Files:**
- Modify: `src/panoscribe/cli.py` (the `transcribe_many` loop, ~lines 458–507)
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: existing `state.items[i].status/error`, `progress.console`, `state_path`.
- Produces: nothing used by later tasks.

- [ ] **Step 1: Write the failing tests.**
  - `test_transcribe_many_prints_failure_reason`: two items; `process_single_video` raises `PanoScribeError("[Errno 2] no such file: x")` for the first and succeeds for the second. Assert that the captured output contains the first item's (shortened) source and the literal `[Errno 2] no such file: x`, plus the summary line `1 done, 1 failed, 0 pending`. Assert the exit code is 0, unchanged.
  - `test_transcribe_many_all_ok_prints_summary_only`: assert there is no error line, the summary is `2 done, 0 failed, 0 pending`, and the state-file path is printed.
- [ ] **Step 2: Run them, and expect FAIL.**
  - Run: `uv run pytest tests/test_batch.py -k "failure_reason or summary_only" -v`
- [ ] **Step 3: Implement the per-item line and the summary.**
  - **Per-item line.** In the `except PanoScribeError as e:` branch, print one line through `progress.console`: `failed: <truncated source>: <escape(str(e))>`. Use `rich.markup.escape` so brackets survive.
  - **Summary.** After the `with progress` block, and only on the non-interrupt path, print the summary line `<n> done, <n> failed, <n> pending`, followed by `State: <state_path>`.
- [ ] **Step 4: Run the tests and the whole suite.**
  - Run: `uv run pytest tests/test_batch.py tests/test_cli.py -v`, and expect PASS.
  - Then run `cct-gate`.
- [ ] **Step 5: Commit.** `fix: transcribe-many shows why an item failed (#184)`

### Task 2: #183 — build the speech engine before any download

**Files:**
- Modify: `src/panoscribe/pipeline.py` (`process_single_video`)
- Modify: `src/panoscribe/cli.py` (`transcribe_many`)
- Test: `tests/test_remote_asr.py` or `tests/test_batch.py` (follow existing patching style: tests patch `panoscribe.cli.*`/`panoscribe.pipeline.*` names)

**Interfaces:**
- Produces: `process_single_video(source, config, output_path, *, ocr_active: bool, output_format: str, console: Console | None = None, asr_engine: AsrEngine | None = None) -> None`.
  - When `asr_engine` is None, the function calls `_build_asr_engine(config)` as its **first** action, before photo routing and before any download, and uses that engine in both the photo and video paths.
  - The API server call stays unchanged and gets the default.

- [ ] **Step 1: Write the failing tests.**
  - `test_remote_settings_error_before_download`: config `asr_backend="remote"`, no model. `download_video` and `download_photo_post` are patched as mocks. Assert `PanoScribeError` matching `PANO_ASR_REMOTE_MODEL`, and that neither mock was called.
  - `test_photo_post_without_audio_still_checks_remote_settings`: a local photo dir with no audio, remote misconfigured. Assert `PanoScribeError` before `scan_photo_dir` results are used. This is Review Focus 4.
  - `test_transcribe_many_stops_before_first_download_on_bad_settings`: two items, remote misconfigured. Assert `download_video` is not called, the exit code is non-zero, the output contains the settings message once, and both items stay `pending` in the state file.
  - `test_local_backend_unchanged`: the default config builds `WhisperTranscriber` without loading a model. Assert that the model loader is not called before `transcribe`.
- [ ] **Step 2: Run them, and expect FAIL.** Run: `uv run pytest -k "before_download or still_checks_remote or stops_before_first or local_backend_unchanged" -v`
- [ ] **Step 3: Implement.**
  - **In `process_single_video`:** add the `asr_engine` parameter and build it first if it is None.
  - **In `transcribe_many`:** build the engine once, before the loop. On `PanoScribeError`, print the message (escaped) and exit 1 without touching item states. Pass `asr_engine=` to every `process_single_video` call.
  - **Verify the lazy load.** Before relying on it, confirm that `WhisperTranscriber.__init__` does no model load. If it does, stop and report.
- [ ] **Step 4: Run the tests and the gate.** Run: `uv run pytest -v`, and expect PASS. Then run `cct-gate`.
- [ ] **Step 5: Commit.** `fix: check remote speech settings before downloading (#183)`

### Task 3: Language probe script and the rapidocr 3.8.1 baseline

**Files:**
- Create: `scripts/probe_ocr_languages.py`
- Create: `tests/test_probe_ocr_languages.py` (pure-function tests only)
- Create: `docs/plans/2026-11-xx-ocr-v6-measurement.md` (the report; this task writes only its "3.8.1 baseline" section; use the real date)

**Interfaces:**
- Produces:
  - `probe_language(ocr_language: str, *, model_set: str | None = None) -> ProbeResult`, where `ProbeResult` is a dataclass with `language: str`, `ok: bool`, `error: str | None`, `det_model: str | None`, `rec_model: str | None` and `text: str`.
    - It builds a real `PanoScribeConfig(ocr_language=..., ocr_device="cpu")`. `model_set` is passed only when not None, because the field doesn't exist before Task 4.
    - It runs `RapidOCREngine.extract_images` on one rendered image.
    - The model names come from rapidocr's log or the loaded session paths.
  - `render_probe_image(text: str, path: Path) -> Path`, which draws black text on white with PIL at ~60 px.
  - `PROBE_TEXT: dict[str, str]`, giving the probe text per `_ISO_TO_LANGREC` value. Use `"Größe Straße 2026"` for `latin`, `"panoscribe 2026"` for `en`, and so on, with one entry per LangRec value the mapping produces.
  - A CLI: `python scripts/probe_ocr_languages.py [--model-set classic|v6] [--json OUT]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_probe_text_covers_every_mapped_value`: `set(PROBE_TEXT) == {v.value for v in _ISO_TO_LANGREC.values()}`.
  - `test_render_probe_image_writes_png`: tmp_path; the file exists, and the image is wider than it is tall.
- [ ] **Step 2: Run them, and expect FAIL.** Run: `uv run pytest tests/test_probe_ocr_languages.py -v`
- [ ] **Step 3: Implement the script.** Real engine; no mocks inside the script.
- [ ] **Step 4: Record the baseline.**
  - On current `main` (rapidocr 3.8.1, unchanged lock), run `uv run python scripts/probe_ocr_languages.py --json /tmp/...`.
  - Copy the table (language, ok/error text, det/rec model, recognised text) into the report's "3.8.1 baseline" section.
  - That table defines "works today" and the classic detector per language (Task 5).
  - Run the tests: expect PASS. Then run `cct-gate`.
- [ ] **Step 5: Commit** the script, the tests and the report section: `chore: OCR language probe and rapidocr 3.8.1 baseline`.

### Task 4: Config — model-set setting and the new knob values

**Files:**
- Modify: `src/panoscribe/config.py` (`_VALID_MODEL_TYPES`, `_OCR_VERSION_CANONICAL`, the new field)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `PanoScribeConfig.ocr_model_set: Literal["classic", "v6"] = "classic"` (env `PANO_OCR_MODEL_SET`, case-insensitive, normalised to lowercase).
  - `_VALID_MODEL_TYPES = {"mobile", "server", "tiny", "small", "medium"}`.
  - `_OCR_VERSION_CANONICAL` gains `"pp-ocrv6": "PP-OCRv6"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_ocr_model_set_default_classic`;
  - `test_ocr_model_set_env_v6_case_insensitive` (`"V6"` → `"v6"`);
  - `test_ocr_model_set_rejects_unknown` (`"v5"` → ValidationError that lists `classic, v6`);
  - `test_model_type_accepts_v6_sizes` (`"Small"` → `"small"`);
  - `test_ocr_version_accepts_ppocrv6`.
- [ ] **Step 2: Run them, and expect FAIL.** Run: `uv run pytest tests/test_config.py -k "model_set or v6_sizes or ppocrv6" -v`
- [ ] **Step 3: Implement** the field and validator, following the existing `_validate_model_type` pattern.
- [ ] **Step 4: Run the tests and the gate.** Run: `uv run pytest tests/test_config.py -v`, and expect PASS. Then run `cct-gate`.
- [ ] **Step 5: Commit.** `feat: PANO_OCR_MODEL_SET setting and PP-OCRv6 knob values`

### Task 5: Model-set resolver, engine integration and the rapidocr 3.10 bump

**Files:**
- Create: `src/panoscribe/ocr/model_sets.py`
- Modify: `src/panoscribe/ocr/rapid_ocr.py` (`_ensure_loaded`: replace the inline det_lang/CH-force/knob block with the resolver's output; keep the CUDA probe, the Det threshold knobs and the error wrapping)
- Modify: `pyproject.toml` (`rapidocr>=3.10,<3.11`), then run `uv lock` (only rapidocr and any dependency it forces may move; report every line that moved)
- Test: `tests/test_model_sets.py` (new); adjust `tests/test_rapid_ocr.py` where it asserts the old inline params

**Interfaces:**
- Consumes: `PanoScribeConfig.ocr_model_set` and the knobs (Task 4); `_resolve_ocr_language` and `_ISO_TO_LANGREC` (existing, in `rapid_ocr.py`); the Task 3 baseline table.
- Produces:
  - `V6_LANGS: frozenset[str]`. This is the exact PP-OCRv6 `small` list from rapidocr 3.10 `default_models.yaml` (`ppocrv6_langs`); copy it verbatim.
  - `resolve_iso(ocr_language: str, detected_language: str | None) -> str | None`. Returns the ISO code in effect (the configured ISO, or the detected one when `"auto"`). Returns None when the config holds a LangRec value such as `"latin"`.
  - `build_model_params(config: PanoScribeConfig, lang: LangRec, iso: str | None) -> tuple[dict[str, object], bool]`. Returns rapidocr params for exactly the keys `Det.lang_type`, `Det.ocr_version`, `Det.model_type`, `Rec.lang_type`, `Rec.ocr_version` and `Rec.model_type`, plus `fell_back` (True when `v6` was asked for but the language has no v6 code).
- **Rules** (D2, D3, D3a, D3b, D4):
  - **Effective version per task** (det and rec separately): the knob if set; otherwise PP-OCRv6 for `v6` with a v6 code; otherwise PP-OCRv4, except Rec PP-OCRv5 for `eslav`, `th` and `el`.
  - **Effective model type:** the knob if set; otherwise `small` for v6 and `mobile` for v4/v5.
  - **Language value for an effective v6 task:** the v6 code is `iso` if it is in `V6_LANGS`. Otherwise it is `{"zh": "ch", "ja": "japan"}.get(iso)` if that is in `V6_LANGS`, else `lang.value` if that is in `V6_LANGS`, else none.
    - When the version came from the set and there is no code, fall back to classic for **both** tasks and log INFO once.
    - When it came from a knob and there is no code, raise `PanoScribeError(f"OCR language {lang.value!r} has no PP-OCRv6 model; supported: ...")`.
  - **Language value for an effective v4/v5 Rec:** the `LangRec` member.
  - **Language value for an effective v4/v5 Det:**
    - `PANO_OCR_DET_LANG` if set;
    - otherwise CH when the Det version is v5 or the Det model type is server (existing rule);
    - otherwise the detector Task 3 recorded for that language on 3.8.1 where it worked (`en` for `en`/`latin`);
    - else `ch` for `ch`/`chinese_cht`/`japan` and `multi` for every other script.
    - Pass `LangDet` members.

- [ ] **Step 1: Write the failing tests** (`tests/test_model_sets.py`, table-driven):
  - classic + `de`: Det `en`/v4/mobile; Rec `LangRec.LATIN`/v4/mobile; `fell_back` False.
  - v6 + `de`: Det and Rec are `"de"`/v6/small.
  - v6 + `ocr_language="latin"`: classic values with `fell_back` True (Review Focus 1).
  - v6 + auto + detected `"xx"` and `None`: `"en"`/v6 (Review Focus 2).
  - v6 + `ko`: classic with Det `multi` (or the baseline value) and `fell_back` True.
  - classic + `ru`: Rec `LangRec.ESLAV`/**v5**/mobile, Det v4.
  - classic + knob `PANO_OCR_REC_OCR_VERSION=PP-OCRv6` + `de`: Rec `"de"`/v6/**small**, Det classic (Review Focus 5).
  - knob Rec v6 + `ko`: raises `PanoScribeError` naming `korean`.
  - classic + `ocr_det_ocr_version="PP-OCRv5"`: Det `LangDet.CH`.
  - `resolve_iso("auto", "pt") == "pt"`; `resolve_iso("latin", "pt") is None`; `resolve_iso("fr", None) == "fr"`.
- [ ] **Step 2: Run them, and expect FAIL.** Run: `uv run pytest tests/test_model_sets.py -v`
- [ ] **Step 3: Implement** `model_sets.py`, wire it into `_ensure_loaded`, then do the bump.
  - **Check first.** Run `uv run python -c "import rapidocr, onnxruntime"` and the Task 3 probe once on 3.10. If onnxruntime needs a newer floor, raise it in `pyproject.toml` and note it in the PR body (D1).
  - **Log line.** Update the "first run may download ~15 MB" log text if the v6 models are larger.
- [ ] **Step 4: Run everything.**
  - `uv run pytest -v` (fix `tests/test_rapid_ocr.py` assertions that pinned the old inline params; `test_default_knobs_still_use_en_det_lang` must still pass unchanged under `classic`).
  - `uv run python scripts/probe_ocr_languages.py --model-set classic` and `--model-set v6`: every mapped language must report `ok`, and the classic det/rec models must match the 3.8.1 baseline wherever the baseline worked.
  - `cct-gate`.
- [ ] **Step 5: Commit.** `feat: rapidocr 3.10 with classic and v6 model sets (replaces the <3.9 cap)`

### Task 6: Unmocked engine check in CI

**Files:**
- Create: `tests/test_ocr_engine_real.py` (marker `engine`)
- Modify: `pyproject.toml` (register the `engine` marker; exclude it from the default `addopts` selection, as with `slow`)
- Modify: `.github/workflows/ci.yml` (new job `ocr-engine`)

**Interfaces:**
- Consumes: `probe_language`, `PROBE_TEXT` (Task 3) and `V6_LANGS` (Task 5).

- [ ] **Step 1: Write the tests.**
  - `test_every_mapped_language_starts[model_set-language]` is parametrised over both sets × every `PROBE_TEXT` key. It asserts `probe_language(...).ok`, and that the recognised text is non-empty and shares at least one 4-character run with the probe text.
  - `test_v6_langs_match_installed_rapidocr` asserts that `V6_LANGS` equals rapidocr's own supported list for PP-OCRv6 small rec. Read that list through `rapidocr.utils.model_resolver.list_supported_langs`, or by parsing the installed `default_models.yaml`. This catches drift on the next bump.
- [ ] **Step 2: Run locally.** Run: `uv run pytest -m engine -v`, and expect PASS. The first run downloads the models.
- [ ] **Step 3: Add the CI job.** Add `ocr-engine` with `if: github.event_name != 'schedule'` and `runs-on: ubuntu-latest`, Python 3.11.
  - Steps: `uv sync --extra dev --extra api`, then `actions/cache@v4` on rapidocr's model directory with key `rapidocr-models-3.10.0-${{ runner.os }}` (find the directory from the installed package), then `uv run pytest -m engine -v`.
  - No `PANO_*` GPU settings; the test forces `ocr_device="cpu"`.
- [ ] **Step 4: Run the gate and push.** Run `cct-gate`, push, and confirm the `ocr-engine` job ran and succeeded at job level (`github_check_runs_for_sha`).
  - The PR body tells the maintainer to add `ocr-engine` as a required check, since branch protection is theirs.
- [ ] **Step 5: Commit.** `ci: unmocked OCR engine check for every mapped language`

### Task 7: Eval samples manifest, model-set recording, per-language summariser

**Files:**
- Modify: `scripts/fetch_eval_samples.py` (`SAMPLES` gains ids 7–16, `"type": "video"`, YouTube Shorts URLs from the design's clip table)
- Modify: `tests/fixtures/eval/README.md` (one manifest entry per new sample: URL, content class, language, fixture path `videos/sample-N.mp4`, ground truth `gt-sample-N.json`)
- Modify: `scripts/eval_ocr.py` (the output JSON gains `ocr_model_set`, `rapidocr_version` via `importlib.metadata.version("rapidocr")`, `language` copied from the ground truth, and `clip` = the video/slides path stem)
- Create: `scripts/summarize_eval.py`
- Test: `tests/test_fetch_eval_samples.py` (extend), `tests/test_summarize_eval.py` (new)

**Interfaces:**
- Produces: `summarize(records: list[dict]) -> dict[tuple[str, str], LangSummary]`, keyed by `(language, ocr_model_set)`.
  - `LangSummary` is a dataclass with `clips: int`, `expected: int`, `matched: int`, `recall: float` (matched / expected, pooled), `segments: int`, `unmatched: int` and `unmatched_rate: float` (pooled from `junk["post_dedup"]` `unmatched_count`/`total_segments`). It also has `raw_recall: float`, pooled from `junk["raw"]` `retained_overlay_recall`, weighted by expected.
  - `verdict(summaries, languages=("en","de","fr","es","pt"), margin=0.02) -> tuple[bool, list[str]]` applies the Global Constraints rule and returns the reasons for any failure.
  - CLI: `python scripts/summarize_eval.py RESULTS_DIR` prints Markdown tables (per clip, per language) and the verdict.

- [ ] **Step 1: Write the failing tests.**
  - `test_samples_include_youtube_ids_7_to_16`: ids are unique; all ten design URLs are present.
  - `test_summarize_pools_by_expected_texts`: two clips with 1/2 and 3/8 matched give recall 0.4, not 0.4375.
  - `test_verdict_fails_when_one_language_drops`: `de` v6 drops by 0.03, so the verdict is False and the reason names `de`.
  - `test_verdict_passes_within_margin`.
  - `test_verdict_fails_when_overall_recall_lower`.
- [ ] **Step 2: Run them, and expect FAIL.** Run: `uv run pytest tests/test_fetch_eval_samples.py tests/test_summarize_eval.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and the gate.** Run them again, and expect PASS. Then run `cct-gate`.
- [ ] **Step 5: Commit.** `chore: YouTube eval samples, model-set recording, per-language summary`

### Task 8: Answer keys (local data; nothing committed)

**Files:** gitignored only. `tests/fixtures/eval/gt-sample-{1..16}.json` on the Linux agent host, plus the fetched media.

- [ ] **Step 1: Fetch.**
  - Run `uv sync --extra dev --extra api --extra photo`, then `uv run python scripts/fetch_eval_samples.py`.
  - Record which of samples 1–6 can no longer be fetched; they are dropped (D5).
- [ ] **Step 2: Extract frames.** For each clip, take one frame every 1 s (`ffmpeg -vf fps=1`) into a scratch dir.
- [ ] **Step 3: Write each key blind (D6).**
  - Use frames and the speech transcript only, **never** any `eval_ocr.py` or OCR output.
  - Write one `ExpectedText` per distinct on-screen text, with `start`/`end` from the frames where it appears.
  - Set `language`. Set `required: false` for tiny, illegible or watermark text.
- [ ] **Step 4: Validate.**
  - `GroundTruth.model_validate_json` passes for every file.
  - Coverage per language is at least 2 clips for each of EN/DE/FR/ES/PT. Otherwise pick one more clip the 2026-11-08 way and repeat Steps 1–3 for it.
  - **Back up the keys.** Copy them to a location outside the repo that the maintainer names, so they aren't lost again (see the Open Brain note). Ask the PO for the location.
- [ ] **Step 5: Report** the list of keys, the expected-text counts per clip, and the dropped samples. Do not commit anything.

### Task 9: Measurement, report, and the default decision

**Files:**
- Modify: `docs/plans/2026-11-xx-ocr-v6-measurement.md` (the Task 3 report)
- Conditionally modify: `src/panoscribe/config.py` (`ocr_model_set` default `"v6"`) and its default test, **only if the verdict passes**.

- [ ] **Step 1: Determinism.** Run one clip twice under `classic`.
  - If the numbers are identical, use single runs.
  - Otherwise, run every configuration 3 times, use the mean, and record the spread.
- [ ] **Step 2: Library-bump check.**
  - Run every clip under `classic` on the v0.9.0 tag (worktree at `~/git/.worktrees/panoscribe/v090-baseline`, rapidocr 3.8.1).
  - Run every clip under `classic` on the branch with Task 5 (rapidocr 3.10).
  - The recall must match, within the Step 1 spread. If it doesn't, stop and report: the bump changed results.
- [ ] **Step 3: Measure.**
  - Run every clip under `v6` with `scripts/eval_ocr.py --junk --output <dir>/<clip>-<set>.json` (`PANO_OCR_MODEL_SET` env, `PANO_OCR_DEVICE=cpu`).
  - Record the wall time per run.
- [ ] **Step 4: Write the report.**
  - Run `uv run python scripts/summarize_eval.py <dir>` and paste its tables and verdict into the report.
  - Add the runtime table, and flag v6 if it is more than 2× slower.
  - Add the raw-vs-filtered recall note, and the list of languages that failed on 3.8.1 (from Task 3).
- [ ] **Step 5: Decide.**
  - **If the verdict passes:** switch the default to `v6`, update the default test, and run `cct-gate`.
  - **If it fails:** leave `classic` and state that in the report.
  - Commit with one of these titles:
    - `feat: PP-OCRv6 becomes the default OCR model set (measured)`;
    - `docs: PP-OCRv6 measurement — classic stays default`.

### Task 10: Docs and changelog for v0.10.0

**Files:**
- Modify: `README.md`:
  - the OCR-knobs paragraph near line 238: model sets, `PANO_OCR_MODEL_SET`, PP-OCRv6 and the `tiny/small/medium` types, rapidocr range;
  - the "first run downloads" note if the sizes changed.
- Modify: `docs/troubleshooting.md`: the `Unsupported rec.lang_type` section now applies to 0.8.1 only, and gains the explicit-knob error case.
- Modify: `CHANGELOG.md` under `[Unreleased]`:
  - Added: model sets and the CI engine check;
  - Changed: the rapidocr range, and the default model set (if Task 9 switched it);
  - Fixed: #183 and #184, and any languages that failed on 3.8.1 and work now.

- [ ] **Step 1: Write the docs.**
  - Plain words. Name the setting and both values, and say how to switch.
  - Say that the default was decided by measurement, and link the report.
- [ ] **Step 2: Run the gate.** Run `cct-gate`, and expect PASS.
- [ ] **Step 3: Commit.** `docs: v0.10.0 OCR model sets, rapidocr range, changelog`

The release itself (version bump PR, tag, publish) is run by the PO with the maintainer, per `docs/release-process.md`, after Tasks 1–10 are merged and main's CI is green.
