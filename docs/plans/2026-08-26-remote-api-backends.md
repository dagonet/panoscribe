# Remote-API backends — issues #83, #84, #85

Tier: T4 (architectural, >200 lines, two new subsystems)

**Status: ANALYSIS AND PLAN ONLY. Not approved for implementation.**

## Context

Issue #77 asked for hosted OCR/ASR because the reporter could not deploy locally. Triage
split that into a local-install track (#78–#82, shipped as v0.3.0) and this API track.

The local track found and fixed real install bugs — macOS/ARM was outright uninstallable,
Python 3.13 was blocked for no valid reason, and a doubled `onnxruntime` install made CUDA
availability depend on install order. **The reporter has not replied since.** It remains
plausible that their problem was one of those bugs and that they need no API at all.

That does not make this work worthless — remote backends were accepted as opt-in on their
merits — but it does mean nothing here is urgent, and the provider choice should not be
made to satisfy a user whose actual constraint is still unknown.

## Corrections to the issues as filed

Verifying the data contracts falsified the main technical claim in #84 and understated a
constraint in both. Update the issue bodies before implementing.

### #84's central premise is wrong

The issue says:

> The downstream UI-chrome filter, bbox aggregation and dedup stages assume word/line-level
> boxes with confidences — check the provider's response shape actually feeds them before
> committing, or document which stages are bypassed.

**Geometry never crosses the protocol boundary.** `aggregate_frame_bboxes` is called from
inside `RapidOCREngine._process_frame` (`ocr/rapid_ocr.py:301`), *not* from `pipeline.py`.
Everything downstream of `extract()` — `filter_by_patterns`, `filter_by_frequency`,
`dedup_segments`, `merge_channels` — reads only `text`, `source`, `start`, `end`, and
optionally passes `confidence`/`language` through.

A text-only backend therefore satisfies `OcrEngine` as written, and **no downstream stage
is bypassed, because no downstream stage was ever on the contract.** The "which stages
are bypassed" framing should be struck.

### What actually breaks instead — four real traps

1. **`ocr_min_confidence` becomes inert.** It is applied in exactly one place:
   `bbox_aggregator.py:139`, per-box, before grouping. Nothing re-applies it after segment
   construction. A backend that never calls the aggregator has **no confidence gate at
   all**, and `config.ocr_min_confidence` (default 0.6) silently stops doing anything.
   Any text-only backend must either apply its own equivalent gate or document the field
   as inoperative for it.

2. **`last_frame_count` is not just logging.** Its docstring (`ocr/protocol.py:37-38`)
   says "used by the CLI for status logging". That understates it: `pipeline.py:193`
   passes it as the `frame_count` **denominator** to `filter_by_frequency`. Consequences
   of a wrong value are mechanical — `0` makes the frequency filter return input unchanged
   (`ui_filter.py:162-163`, silently off); under-reporting inflates `count / frame_count`
   and over-drops legitimate text. Fix the docstring as part of this work.

3. **`source="ON-SCREEN"` must be passed explicitly.** `TranscriptSegment.source` defaults
   to `"SPEECH"` (`output.py:35`). An OCR backend that forgets it produces segments that
   look like speech to every downstream filter.

4. **`mask_zones` needs local pixels.** UI-chrome masking (`ui_filter.py:56-84`) operates
   on the frame buffer *before* inference. A backend that hands a whole video or a URL to
   a provider cannot mask at all. Frames must be materialised and masked client-side
   before upload — which also means per-frame upload cost is unavoidable.

### #83 — two constraints to add

- **`TranscriptSegment.end` is required** (`output.py:34`, no default). Pydantic raises at
  construction. A provider returning only start offsets must synthesise `end` before
  building segments. Merge depends on both sides: `_overlaps` (`output.py:183-189`) reads
  `speech.start`, `speech.end`, `ocr.start`, `ocr.end`.
- **The `translate` split is subtler than the issue states.** `whisper.py:174,185` sets
  per-segment `language="en"` while still returning `info.language` — the *source* — as
  `detected_language`, deliberately, so OCR auto-resolution picks the right recogniser for
  on-screen text that was never translated. A remote backend offering translation must
  reproduce that split exactly, not collapse it.

### Both — no credential precedent exists

Grepping `src/` for `api_key|token|secret|password|credential|SecretStr|auth` returns
**only prose comments**. There is no secret-shaped field anywhere, no `SecretStr` import,
nothing to copy. The closest analogue is the Ollama host — plain `str` config fields
(`config.py:101-110`). This work would introduce the project's first credential, so the
handling pattern is a decision to make deliberately rather than a convention to follow.

Config is clean of leakage today (no `model_dump()`/`repr(config)` in any log call), but
that is a "clean now" observation, not a structural guarantee.

## Design

### Shared groundwork (do first, small)

- Establish the credential pattern. Recommended: `pydantic.SecretStr` fields, read from
  `OMNI_*` env vars via the existing `BaseSettings` (`config.py:47-51`), never logged,
  never written to `temp_dir` or output. Add a test asserting the secret does not appear
  in a config repr or in any emitted log record.
- Fix the `last_frame_count` docstring (trap 2 above) so the next implementer sees it.
- Add a `[remote]` optional-dependency group.

Import guarding **must** follow Pattern A from `merge/llm_cleanup.py:59-67` — module-top
`try/except ImportError` binding the name to `None`, plus a deferred, actionable
`OmniScribeError` at point of use. Not the function-local Pattern B: a module-scope name
is what makes `unittest.mock.patch` work, and every test in this repo patches at the
import site.

### #83 — remote ASR

Satisfies `AsrEngine` (`asr/protocol.py`), whose entire surface is one method.

Provider target: an **OpenAI-compatible `/v1/audio/transcriptions` endpoint**, not a
specific vendor. Verified: that API supports `response_format=verbose_json` with
`timestamp_granularities: ["segment"]`, which yields the `start`/`end` the merge stage
requires. A generic endpoint also covers self-hosted servers, which may serve the #77
reporter better than any commercial vendor.

Cost shape is favourable: one upload per clip.

Must reproduce: segment-level `start`/`end`; `source` left at `"SPEECH"`; `language`
per-segment; the translate split above; and `confidence` — note the existing scale
collision (ASR uses a negative `avg_logprob`, OCR a 0–1 mean, no validator on the field,
documented at `output.py:233-236`). Simplest correct choice is `confidence=None` unless the
provider returns a comparable log-prob. Do not invent a 0–1 value that silently changes
meaning.

### #84 — remote OCR

Now that geometry is known not to cross the boundary, the two provider classes differ in
**quality**, not in structural feasibility:

| | Class A — dedicated OCR API | Class B — vision LLM |
|---|---|---|
| Examples | Google Cloud Vision, Azure, Textract | OpenAI-compatible chat with images |
| Returns | `boundingPoly` vertices + confidence | prose only |
| Can reuse `aggregate_frame_bboxes` | Yes | No |
| `ocr_min_confidence` | Works | **Inert** unless a substitute gate is added |
| Line/column grouping | Provider or existing aggregator | Whatever the model emits |

Class A is the closer drop-in and keeps the confidence gate meaningful. Class B is what
`IMPLEMENTATION_PLAN.md:311` already contemplates as a *local* vision-LLM backend — these
two may share one abstraction, and that overlap should be settled before either is built.

**The cost problem stands regardless of class.** Frames are sampled at `ocr_sample_fps`
and scene-change filtered, but a short clip is still dozens of images, hence dozens of
billed calls per transcript — and masking forces client-side materialisation, so
per-frame upload cannot be avoided. Mitigations to evaluate before writing code: batching
where the provider supports it, and surfacing an estimated call count before a run starts.

`extract_images` must also be implemented — the photo-post path uses it — and it raises
`ValueError` when `len(timestamps) != len(image_paths)` (`rapid_ocr.py:409-412`).

### #85 — README positioning

Ships in the same PR as whichever of #83/#84 lands first, never before. Reword
`README.md` "Fully local" to "local by default", stating that remote backends are explicit
opt-in and that **user audio or video frames leave the machine** when enabled.

## Testing strategy

The repo has **no HTTP-level mocking pattern** — no `respx`, no `httpx.MockTransport`, no
cassettes. The only precedent is client-object mocking (`tests/test_llm_cleanup.py:40`,
patching `omniscribe.merge.llm_cleanup.Client` at the import site).

Decision needed: reuse the client-object pattern (consistent, cheap, but never exercises
serialisation or error mapping) or introduce `httpx.MockTransport` (real request/response
shapes, catches contract drift, but is a new pattern for the repo to maintain). For code
whose entire job is talking HTTP to a third party, the latter is probably worth it — but
it is a deliberate new convention, not an incidental choice.

Coverage is `fail_under = 95` with no `omit` and no `exclude_lines`, so every line of a new
backend counts. Error paths, retries and timeouts all need tests, not just the happy path.

## Sequencing

1. Shared groundwork — credential pattern, docstring fix, `[remote]` extra.
2. #83 remote ASR — smaller, better-defined, favourable cost shape.
3. Re-evaluate #84 with #83's plumbing proven, and settle the Class A/B question and the
   overlap with the local vision-LLM roadmap item first.
4. #85 ships with whichever backend lands first.

## Open decisions — resolve before implementing

1. **Should this be built at all yet?** #77 is silent. Building a backend for an unstated
   constraint risks targeting the wrong provider shape entirely.
2. **Provider strategy** — generic OpenAI-compatible endpoint, one named vendor, or a
   pluggable provider layer.
3. **#84 class** — dedicated OCR API (keeps the confidence gate) or vision LLM (loses it,
   but converges with the existing local vision-LLM roadmap item).
4. **Test fidelity** — client-object mocks or `httpx.MockTransport`.
