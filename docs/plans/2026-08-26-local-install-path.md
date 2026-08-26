# Local install path — issues #78, #79, #80, #81, #82

Tier: T3

## Context

Issue #77 asked for remote-API OCR/ASR because the reporter could not deploy models
locally. Triage split that into a local-install track (#78–#81) and an API track
(#82–#85). This plan executes the local track plus #82, the `AsrEngine` protocol.

**#83, #84, #85 are explicitly held** — the #77 reporter never supplied a platform or
error, and no provider has been chosen. Building a remote backend now would be guessing.

Verification during planning **falsified three claims in the issues as filed**. Those
corrections drive the design below, and each issue needs its body updated:

| Claim as filed | Verified reality |
|---|---|
| #78: no macOS wheels | **Correct.** `uv pip compile --python-platform macos` fails: `onnxruntime-gpu>=1.20.0 has no wheels with a matching platform tag (macosx_13_0_arm64)`. True for every version 1.20–1.29. |
| #78: no linux-aarch64 wheels | **Too broad.** 1.29.0 ships `manylinux_2_34_aarch64`. `aarch64-manylinux_2_34` resolves; `_2_28` and `manylinux2014` still fail. The real statement is "none below glibc 2.34". |
| #78 / `pyproject.toml:7`: Python 3.13 blocked because ORT ships win wheels only for cp311/cp312 | **Wrong.** `onnxruntime-gpu` has shipped cp313 `win_amd64` since 1.20.0 and cp314 since 1.24.1. `uv pip compile --python-version 3.13` resolves 59 packages clean. Nothing blocks 3.13. |

And surfaced a defect no issue records:

> **`onnxruntime` and `onnxruntime-gpu` are both installed, into the same
> `onnxruntime/` package directory.** `faster-whisper` hard-requires
> `onnxruntime<2,>=1.14`; this project declares `onnxruntime-gpu>=1.20,<2.0`. Both
> resolve to 1.24.4 and unpack over one another. `CUDAExecutionProvider` is present on
> the dev machine today **by install order**, not by any resolution guarantee. A clean
> re-sync can silently land the CPU build last and drop CUDA.

Fixing that is folded into #78 — it is the same edit.

## Decisions

1. **Marker-gate, don't add a `[gpu]` extra.** Markers auto-select per platform, so the
   Windows/CUDA experience stays byte-identical with no new install incantation. An
   extra would force every existing user to relearn the install command.
2. **Hard-fail when `device=cuda` and CUDA is absent**, naming the exact remedy. A silent
   ~30x CPU slowdown is worse than a clear error, and this preserves the existing
   `rapid_ocr.py:8` design note ("No runtime CUDA→CPU fallback"). No `auto` value.
3. **Lift `requires-python` to `<3.14` and add 3.13 to the CI matrix.** 3.13 resolves ORT
   1.29.0 where 3.11 resolves 1.24.4 — the matrix is what would catch a behavior delta
   between them, so lifting the cap without it would be an untested claim.

## PR 1 — packaging (#78)

`pyproject.toml` only. No source changes.

Replace the unconditional `onnxruntime-gpu>=1.20,<2.0` with a marker pair. PEP 508 has no
`not` operator, so the CPU marker is written as the explicit complement, and
`platform_machine` is compared with `==` rather than the `in 'x86_64 AMD64'` substring
idiom (which would also match a bare `AMD`):

- GPU marker: `(sys_platform == 'win32' or sys_platform == 'linux') and (platform_machine == 'x86_64' or platform_machine == 'AMD64')`
- CPU marker: `(sys_platform != 'win32' and sys_platform != 'linux') or (platform_machine != 'x86_64' and platform_machine != 'AMD64')`

Add **one** entry to the existing `[tool.uv] override-dependencies` list — the mechanism
already used for `opencv-python ; sys_platform == 'never'`:

```
"onnxruntime>=1.20,<2.0 ; <CPU marker>"
```

**The version bound is load-bearing.** A uv override *replaces* the requirement globally;
an unversioned `onnxruntime ; <marker>` would discard the project's `>=1.20,<2.0`,
faster-whisper's `<2,>=1.14`, and rapidocr's bounds, so CPU platforms would resolve ORT
2.0 unconstrained the day it ships. Carrying the bound in the override also makes the
question of whether overrides replace direct deps moot — so do **not** add a separate
direct `onnxruntime` dependency line. One override entry, nothing else.

That override is what suppresses `faster-whisper`'s transitive plain `onnxruntime` on GPU
platforms and ends the double-install. On GPU platforms `faster-whisper` imports
`onnxruntime` and gets it from `onnxruntime-gpu`, which ships the same top-level module;
`faster_whisper/vad.py` pins `providers=["CPUExecutionProvider"]` for Silero, so
`vad_filter=True` (`whisper.py:163`) keeps working on both branches.

Note in a comment that `override-dependencies` is uv-specific: a plain
`pip install omniscribe` will still pull both distributions. That is the status quo, not
a regression, but it should be written down.

Routing this produces: macOS → CPU build. Windows ARM → CPU build. linux-aarch64 → CPU
build, which sidesteps the glibc-2.34 cliff entirely rather than depending on it.

Also: `requires-python = ">=3.11,<3.14"`, replace the incorrect cp311/cp312 comment with
what is actually true, and add the 3.13 classifier (`pyproject.toml:30-32`).

`.github/workflows/ci.yml:19` is a single hardcoded `python-version: "3.11"`, not a
matrix, so this is a restructure. Two changes:

- Turn the `test` job into a matrix over Python **3.11 and 3.13**.
- Add a cheap **`resolve` job** that runs `uv lock --check` and a `uv pip compile` per
  platform target (macos, windows, linux, aarch64), asserting the correct ORT
  distribution is selected for each.

The `resolve` job is the one that actually guards this PR. A Windows *runner* would test
the platform PR 1 changes, but every model boundary is mocked (`tests/test_rapid_ocr.py:95`),
so a Windows job would pull ~1 GB of `nvidia-*` wheels to exercise nothing but resolution —
which `uv pip compile --python-platform windows` proves on Linux for free. The 3.13 job
earns its place by catching resolution and import breakage under the lifted cap, not a
1.24-vs-1.29 behavior delta, which mocked tests cannot see either way.

Regenerate `uv.lock`.

### Verification (PR 1)

Resolution dry-runs, none of which install anything:

- `uv pip compile pyproject.toml --python-platform macos --python-version 3.12` → must now **succeed** and select `onnxruntime`, not `onnxruntime-gpu`.
- `--python-platform aarch64-manylinux_2_28` → must now **succeed** (it fails on main).
- `--python-platform linux --python-version 3.11` → must still select `onnxruntime-gpu` and must **not** list plain `onnxruntime`.
- `--python-version 3.13` → succeeds.

`uv pip compile` ignores `uv.lock` entirely, so those four prove nothing about the lock or
the image. Also required:

- **`uv lock --check`** — the lock must be current with the edited `pyproject.toml`.
- **`docker build`** must succeed. `Dockerfile:25,35` runs `uv sync --frozen` against the
  regenerated lock, and `docker build` appears in neither `ci.yml` nor the gate — so PR 1
  can pass every other check and still break the image.

Then, on this Windows/4090 box, the regression that actually matters. **Delete `.venv`
first** — both distributions declare `top_level.txt = onnxruntime` and share one
directory, so uninstalling the CPU dist from the current venv deletes files ORT-GPU also
owns and proves nothing:

- `rm -rf .venv` → `uv sync` → `uv run python -c "import onnxruntime as ort; print(ort.__version__, ort.get_available_providers())"` → `CUDAExecutionProvider` must still be listed, and `importlib.metadata` must now show **only** `onnxruntime-gpu`.
- A **second** `uv sync` must be a no-op (idempotence).
- `bash hooks/run-gate.sh` green.

### Known non-goal for PR 1

Marker-gating keys on *platform*, not on GPU *presence*. A Windows or Linux x86_64 user
with no NVIDIA card — plausibly the #77 reporter — still pulls ORT-GPU and the four
`nvidia-*` packages. PR 1 does not help them; PR 2's error and PR 4's docs do. Say so in
the PR body rather than implying #78 fixes every install complaint.

## PR 2 — fail fast on a missing CUDA provider (#81)

New `src/omniscribe/device.py`. Keep it small: coverage is `fail_under = 95` with **no
`omit` and no `exclude_lines`**, so every line of a new module counts.

One function per runtime, because the two runtimes answer the question differently:

- OCR / ONNXRuntime → `"CUDAExecutionProvider" in onnxruntime.get_available_providers()`
- ASR / CTranslate2 → `ctranslate2.get_cuda_device_count() > 0`. Do **not** probe ORT for
  the ASR path; faster-whisper does not use ORT for inference, and a wrong probe would
  fail a working setup. `get_cuda_device_count` is imported in `ctranslate2/__init__.py`
  under a silently-passing `except ImportError`, so it can legitimately be absent —
  wrap the probe in `except Exception` and treat any failure as "no CUDA".

Both raise `OmniScribeError` naming the remedy verbatim — `OMNI_WHISPER_DEVICE=cpu`,
`OMNI_WHISPER_COMPUTE_TYPE=int8`, `OMNI_OCR_DEVICE=cpu`. Probe only when the configured
device is `cuda`; a `cpu` config must never import or touch a CUDA symbol.

**Do not link `docs/troubleshooting.md` from the message yet** — PR 4 creates that file.
PR 4 adds the pointer once the target exists.

**Scope the promise honestly.** These probes detect an absent CUDA *runtime*. They do not
detect the failure mode most likely on Windows: cuDNN sub-library resolution, whose
failures are `logger.debug`-only in `asr/whisper.py:92-100`. A box with CUDA but broken
cuDNN still reaches a raw CTranslate2 error. Say that in the PR body; do not claim the
probe catches every GPU misconfiguration.

Call sites: `asr/whisper.py:_ensure_loaded` (before `WhisperModel(...)`, ~:145) and
`ocr/rapid_ocr.py:_ensure_loaded` (before `RapidOCR(params=...)`, ~:252). Probe at the
top of each, so the failure lands before the model load rather than inside it.

### Moved baseline — must not be missed

`tests/test_rapid_ocr.py:30-44` `_make_config()` defaults `ocr_device: "cuda"`, and
`tests/test_rapid_ocr.py:131,146` assert `use_cuda is True`. Adding a probe to
`_ensure_loaded` makes **every one of those tests hit the new CUDA check**, which fails on
the Linux CI runner (no GPU). This is exactly the VERIFICATION_PLAYBOOK rule-4 case.

This is roughly **25 sites, not 2** — every `RapidOCREngine(...).extract(...)` in that
file inherits the cuda default. Use **one module-scoped autouse fixture** in
`tests/test_rapid_ocr.py` that patches the probe at its import site, rather than editing
each test. That is not the same thing as making the probe no-op under pytest, which
remains forbidden — the fixture is explicit, local, and leaves the probe's own tests free
to exercise the real function.

`tests/test_whisper.py:19` already uses `cpu`, so the ASR tests are safe.
`tests/test_ocr_protocol.py:26` constructs with a default cuda config but never calls
`extract`, so it passes only while the probe stays inside `_ensure_loaded` — note this
explicitly, because PR 3 mirrors that conformance test for ASR and would walk into it.

### Verification (PR 2)

New tests, patching `onnxruntime.get_available_providers` / `ctranslate2.get_cuda_device_count`:

- provider present + `device=cuda` → no raise, model constructed
- provider absent + `device=cuda` → `OmniScribeError`, message contains each of the three env vars
- `device=cpu` with provider absent → no raise, and the probe is not called
- both call sites covered, ASR and OCR independently

Full suite green on this machine (which HAS a 4090 — so also confirm the CI-shaped case
by patching, not by relying on local hardware). `bash hooks/run-gate.sh` green.

## PR 3 — `AsrEngine` protocol (#82)

Pure refactor, no behavior change. Add `src/omniscribe/asr/protocol.py` mirroring
`src/omniscribe/ocr/protocol.py:28` — `typing.Protocol`, `@runtime_checkable`, not an ABC.
Extract exactly the interface `WhisperTranscriber` already satisfies:
`transcribe(audio_path: Path) -> tuple[list[TranscriptSegment], str]`. Type-hint the
pipeline's ASR slot against it; leave construction at `pipeline.py:133,150` where it is.

Conformance test modeled on `tests/test_ocr_protocol.py`. **`tests/test_whisper.py` must
pass unchanged** — if it needs edits, the interface was extracted wrong.

## PR 4 — docs (#79, #80)

Written last, so it can quote PR 2's real error text rather than an invented one.

`README.md` — a "Running without a GPU" block. Insert after `## Requirements` (:262),
which currently leads with the NVIDIA GPU line. Must include
`OMNI_WHISPER_COMPUTE_TYPE=int8`; the existing Docker CPU example at `README.md:250`
omits it and is wrong as written — fix that line too. Mention the speed penalty so the
CPU path is not oversold. Cross-link from `docs/configuration.md` `### ASR` (:27) and
`### OCR` (:38).

New `docs/troubleshooting.md`: model downloads (faster-whisper pulls ~1.6 GB from Hugging
Face on first run; RapidOCR ~15 MB), `HF_ENDPOINT` mirrors, `HF_HOME` relocation, offline
pre-seeding, CUDA-not-found (→ the PR 2 error), the macOS/ARM install story after PR 1,
and ffmpeg. Link it from `## Requirements`.

**Do not publish the CPU incantation until it has been run.** The Dockerfile already
pre-downloads models with `device='cpu', compute_type='int8'` (`Dockerfile:28,31`), so the
path is known-good in principle — but the documented env-var form must be executed
end-to-end on a short fixture before it ships.

## Sequencing

One PR at a time, one agent at a time — this is a shared checkout, so no parallel branches.
Each PR: branch → implement → `bash hooks/run-gate.sh` → PR → **green Actions run on the
head SHA** → squash-merge → delete branch.

PR 1 → PR 2 → PR 3 → PR 4. PR 3 is independent and could move, but the order keeps the
docs last so they describe shipped behavior.

Issue bodies for #78 (and the `<3.13` note) need correcting to match the verified facts in
the Context table — do that when PR 1 merges, not before.
