# Real-Whisper end-to-end test

Tier: T3

## Problem

No test anywhere runs actual Whisper. The 607-test suite covers mocked paths only, so
the failure class it cannot catch is exactly the one that breaks users: the model fails
to load, the CUDA/CPU shim misbehaves, faster-whisper changes its segment shape, or the
audio decode path is wrong. `conftest.py:44` `silence_wav_path` synthesizes 1s of
silence and is explicitly documented as mock-only, never exercising a decoder.

## Existing mechanism to reuse (verified)

- `pyproject.toml [tool.pytest.ini_options]`:
  `addopts = "-ra -q --strict-markers -m 'not integration and not eval'"`.
- Four markers declared. `integration` (2 uses) and `eval` (1 parametrized x6) are
  deselected — that is the "8 deselected".
- **`slow` and `gpu` are declared but have ZERO uses and are NOT in the deselect
  expression.** A `@pytest.mark.slow` test added today would run on every PR. Adding
  the marker is not sufficient; the addopts expression must be extended.

## ASR facts

- `faster_whisper` (`WhisperModel` + `BatchedInferencePipeline`), imported at
  `asr/whisper.py:119` after `_register_nvidia_dll_dirs()` (`:21`). Lazy load in
  `_ensure_loaded` (`:138`), model built `:148-151`.
- Defaults (`config.py:54-59`): `whisper_model="large-v3-turbo"`,
  `whisper_device="cuda"`, `whisper_compute_type="float16"`. `env_prefix="PANO_"`
  (`config.py:48`), so `PANO_WHISPER_MODEL` / `PANO_WHISPER_DEVICE` /
  `PANO_WHISPER_COMPUTE_TYPE` all work.
- `whisper.py:140` calls `require_cuda_for_asr` when device == "cuda". A CPU test MUST
  set `PANO_WHISPER_DEVICE=cpu` and a CPU-valid compute type (e.g. `int8`).
- `whisper.py:143` logs "first run may download ~1.5 GB" for the default model. Use
  `tiny` (~75 MB) for the test.
- `pipeline.py:134,167` binds `WhisperTranscriber` directly — there is NO injection
  seam. The test either drives the pipeline/CLI or constructs `WhisperTranscriber`.

## Fixture problem

`tests/fixtures/` holds only `eval/README.md` and `eval/example-gt.json`. No media.
`.gitignore` excludes `*.mp4` (:32), `*.wav` (:34), and the eval video/slide dirs
(:59-62). Real eval samples are fetched by `scripts/fetch_eval_samples.py` and are
gitignored, and `test_eval_sample_baseline` skips when they are absent.

So this test needs a small, committed, real-speech audio clip. Resolve it in this
order and state which was used:

1. A short (2-5s) clearly-licensed public-domain / CC0 speech clip committed under
   `tests/fixtures/e2e/`, with a `.gitignore` negation so it is tracked despite the
   `*.wav` rule, plus a `README.md` recording source, license, and exact provenance.
   Prefer a lossless small format. Keep it under ~200 KB.
2. If no suitable clip can be sourced without network access at author time, generate
   speech offline with a tool available in the environment and commit the output,
   documenting the generator command.
3. If neither is possible, STOP and report — do not fake it with silence or noise, and
   do not write a test that asserts nothing meaningful.

## Scope

1. `tests/test_e2e_whisper.py`, marked `@pytest.mark.slow`. It must:
   - force CPU (`PANO_WHISPER_DEVICE=cpu`, CPU-valid compute type) and
     `PANO_WHISPER_MODEL=tiny` via monkeypatched env or an explicit `Config`;
   - run real transcription over the committed clip;
   - assert on properties robust to model nondeterminism: at least one segment, times
     monotonic and within clip duration, non-empty text, a detected language, and
     `asr_logprob` populated and negative (the post-split ASR field) with
     `ocr_confidence` unset.
   - Do NOT assert an exact transcript string. A loose keyword/fuzzy check against the
     known utterance is acceptable; an exact-match assertion is not.
2. Extend the addopts deselect expression so `slow` does not run in the default suite.
   Verify the deselected count moves 8 -> 9 and that `-m slow` selects it.
3. A CI job that actually runs it — the `test` job is the coverage gate on every PR and
   is the wrong host. Add a separate opt-in job (a `schedule:` nightly trigger and/or
   `workflow_dispatch`), on `ubuntu-latest`, CPU only. Cache the model: CI currently
   has uv caching only (`enable-cache: true`) and NO `actions/cache` for model weights,
   so an uncached run re-downloads every time.
4. Document in `docs/` how to run it locally (`uv run pytest -m slow`).

## Verification

- `bash hooks/run-gate.sh` -> PASS. Default suite must be UNCHANGED at 607 passed, with
  deselected rising 8 -> 9. Report actual numbers.
- `uv run pytest -m slow -v` -> the e2e test actually runs and passes. Paste the real
  output including duration and the transcript produced.
- Confirm the test fails correctly if the model cannot load (temporarily point
  `PANO_WHISPER_MODEL` at a bogus name) — it must fail loudly, not skip silently.
- Confirm the fixture is genuinely tracked by git.

## Out of scope

GPU testing, the `gpu` marker, model-accuracy benchmarking, and any change to ASR
production code. If an injection seam looks necessary, stop and report rather than
refactoring `pipeline.py`.
