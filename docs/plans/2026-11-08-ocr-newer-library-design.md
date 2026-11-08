# Newer OCR library support (rapidocr 3.10 / PP-OCRv6), plus #183 and #184 — design

Status: draft for the maintainer's approval, 2026-11-08. Target release: **v0.10.0**.
Decisions marked *(PO call)* were made by the PO, not the maintainer; the
maintainer can overturn them when reviewing this document.

## Why

- **What broke.** rapidocr 3.9.0 (2026-06-23) made PP-OCRv6 its default detection and recognition model.
  - PP-OCRv6 is one multilingual model. It accepts per-language codes (`de`, `fr`, `en`, `ch`, `japan`, ...), but not the grouped values panoscribe sends today (`latin`, `eslav`, `korean`, `arabic`, ...).
  - The published 0.8.1 allowed `rapidocr<4.0`, so every fresh install failed OCR for all languages except English, Chinese and Japanese.
- **The stopgap.** v0.9.0 capped `rapidocr<3.9` (#180). That works, but it pins panoscribe to an aging library and keeps the new model out of reach.
- **The outside attempt.** PR #174 tried passing raw ISO codes. It breaks rapidocr 3.8.x, leaves non-Latin languages broken and changes the detection language; see the review comment on #174.
- **What the maintainer cares about.** Burned-in captions and text overlays on TikTok and YouTube. **English, German, French, Spanish and Portuguese must read at least as well as today.**

## Goals

1. panoscribe runs on the current rapidocr (3.10) for **every language it maps today**, and the #180 cap is replaced.
2. The PP-OCRv6 models are available. They become the default **only if the measurement in D5 says so**.
3. A measurement on real clips in all five languages decides that, and its report is kept in the repo.
4. An **unmocked** check in CI makes every mapped language actually start the engine. Today every OCR test mocks `RapidOCR`, which is why the 3.9 change went unnoticed.
5. **#183:** check the remote speech-recognition settings before any download.
6. **#184:** `transcribe-many` prints why an item failed, plus a summary.

## Non-goals

- Picking a different model per language. This comes back as a follow-up only if the measurement shows a large win for some languages and a clear loss for others.
- Remote OCR (#84 stays parked).
- Retuning the filter, dedup and cleanup stages for the new model. If the measurement shows the new model needs that, it is separate work, and the default stays `classic` until then.
- Merging PR #174. It stays open; the maintainer decides later.

## Anti-goals: failure even if it "works"

- Any language that works today fails to start on a fresh install.
- Reading quality for the five languages changes without a measurement.
- More junk text (stray letters, background fragments) in transcripts.
- Third-party clips or answer keys end up in the repository.

## Verified facts (rapidocr wheels, read 2026-11-08)

| | 3.8.x (today's lock: 3.8.1) | 3.10.0 |
|---|---|---|
| Default det / rec | PP-OCRv4 mobile | PP-OCRv6 `small` |
| `lang_type` passed as plain `str` | **rejected** (`TypeError`: must be Enum) | accepted (validated against model routes) |
| `OCRVersion` members | v4, v5 | v4, v5, v6 |
| `ModelType` members | mobile, server | mobile, server, tiny, small, medium |

- **PP-OCRv6 (3.10) supported languages**, the same list for det and rec: `ch`, `chinese_cht`, `en`, `japan`, plus Latin-script ISO codes, including `de fr es it pt nl pl sv da no fi tr cs sk hu ro ca vi id ms sw tl`. Also accepted are aliases `zh` → `ch` and `ja`/`jp` → `japan`.
  - It has **no** `latin`, `eslav`, `cyrillic`, `korean`, `arabic`, `devanagari`, `th`, `el`, `ta`, `te`, `ka` or `multi`.
- **PP-OCRv4 rec (mobile)** routes `arabic ch chinese_cht cyrillic devanagari en japan ka korean latin ta te`. **PP-OCRv4 det (mobile)** routes `ch en multi`.
- **PP-OCRv5 rec (mobile)** routes `ch korean latin eslav en th el arabic cyrillic devanagari ta te`.

Source: `rapidocr/utils/parse_parameters.py`, `default_models.yaml` and `utils/model_resolver.py` in each wheel. The builder re-checks these against the installed wheel before relying on them.

## Decisions

**D1 — Library range.** Require `rapidocr>=3.10,<3.11`, and move the lock to 3.10.0 *(PO call)*.
- **Raising the floor** removes the dual code path: 3.8 needs Enum values, v6 needs plain strings, so supporting both would mean branching on the installed version everywhere.
- **The tight upper cap** means a fresh install only ever gets a version CI has tested. Each new rapidocr minor release becomes a deliberate bump. This is what 0.8.1 lacked.
- **Check early.** First confirm that 3.10 and the v6 models load with the project's `onnxruntime` / `onnxruntime-gpu` range (`>=1.20,<2.0`). If they need a newer floor, raise it in the same change and say so in the CHANGELOG.

**D2 — Two model sets behind one setting:** `PANO_OCR_MODEL_SET` = `classic` | `v6` *(PO call on the name)*.
- **`classic`** reproduces today's models on the new library. To do that it pins `Det.ocr_version`/`Rec.ocr_version` = PP-OCRv4 and `model_type` = mobile, with today's language values (`LangRec` members, detection `en` for Latin script, as now). It is today's behaviour, made explicit, because 3.10's defaults are no longer today's.
- **`v6`** uses PP-OCRv6 `small` for detection and recognition, passing the ISO code of the resolved language (`de`, `fr`, ..., `en`, `ch`, `japan`).
- **Default:** `classic` until D5 says otherwise.

**D3 — Languages v6 doesn't cover.** Under `v6`, a language without a v6 route uses the `classic` models automatically, for detection **and** recognition, with one INFO log line. A language that works under `classic` never fails under `v6`.

**D3a — "Every mapped language" means all of them on 3.10** *(PO call)*.
- Every value `_ISO_TO_LANGREC` produces has a route on 3.10: PP-OCRv4 mobile has `arabic ch chinese_cht cyrillic devanagari en japan ka korean latin ta te`, and PP-OCRv5 mobile has `eslav th el`.
- So `classic` uses v4 where v4 has the language. For `eslav`, `th` and `el` it uses v5 mobile **recognition**, while detection stays on today's v4 model (detection and recognition versions are set independently). The CH-det rule applies only when the *detection* version is v5.
- Some of those three may already fail on 3.8.1. If so, they get fixed as part of this work. Nothing is dropped from the mapping, and D7 covers every mapped language.
- Record in the measurement report which languages failed on 3.8.1.

**D3b — Fallback vs explicit knobs** *(PO call)*.
- **The automatic fallback (D3)** applies only when the set is chosen with `PANO_OCR_MODEL_SET=v6`.
- **Explicit knobs are never silently changed.** If a user sets `PANO_OCR_REC_OCR_VERSION=PP-OCRv6` (or the det knob) and the language has no v6 route, the run fails at engine start with a `PanoScribeError` that names the language and lists the supported ones.

**D4 — Existing knobs keep working.**
- `PANO_OCR_{DET,REC}_{MODEL_TYPE,OCR_VERSION}` and `PANO_OCR_DET_LANG` still override the model set.
- They now also accept `PP-OCRv6` and `tiny`/`small`/`medium`.
- A combination rapidocr can't route fails at engine start, with rapidocr's own "supported languages" message wrapped in `PanoScribeError`.
- The server/v5 → CH detection override stays for `classic`.

**D5 — Measurement and the rule for the default.**
- **Clips.**
  - The existing six eval samples (`tests/fixtures/eval/README.md`).
  - Ten new YouTube Shorts picked 2026-11-08, listed below.
- **Runs.**
  - Every clip runs through `scripts/eval_ocr.py --junk` under `classic` and under `v6`, on CPU, with identical sampler settings.
  - Then `classic` on 3.10 vs 3.8.1 on the same clips: it must give the same recall within run noise. That proves the library bump alone changes nothing.
- **Rule.** `v6` becomes the default iff, for **each** of EN, DE, FR, ES and PT (averaged over that language's clips):
  - recall(v6) ≥ recall(classic) − 0.02;
  - junk, meaning `unmatched_rate` after the full filter chain, is no higher than classic + 0.02;
  - mean recall across all clips is not lower than classic's.

  Otherwise `classic` stays the default and `v6` is an opt-in.
- **Speed.** Runtime per clip is reported but is not a gate. If `v6` is more than 2× slower on CPU, the report says so plainly for the maintainer.
- **Report.** The result goes to `docs/plans/2026-11-xx-ocr-v6-measurement.md`, with per-clip and per-language tables and the verdict.
- **How a language's number is computed** *(PO call)*: recall per language is **pooled over all expected texts of that language's clips**, not averaged per clip, so one short clip can't swing it. The same goes for the junk rate, pooled over segments.
- **Run noise.** Sampling (fixed fps plus the scene-change threshold) and CPU ONNX inference are expected to be deterministic. The builder confirms this by running one clip twice: both runs must give identical numbers. If they don't, run every configuration 3 times and use the mean, and the report states the observed spread.
- **Who runs it and where** *(PO call)*: agents on the Linux agent host, on CPU. Clips are fetched with `scripts/fetch_eval_samples.py`. This is a local run, not CI.
- **Existing six samples.** Their clips and keys are gitignored and are not on the Linux host. If the maintainer can supply the keys, they are used. Otherwise the clips are re-fetched and their keys rewritten the D6 way. Any sample that can no longer be fetched is dropped, and the report says so.
- **Language coverage.** It is taken from each key's `language` field. If a language ends up with fewer than two clips, one more clip is picked the 2026-11-08 way before measuring.

**D6 — Answer keys for the new clips.**
- **Who writes them:** the PO or an agent, by reading extracted frames, since the maintainer doesn't read FR/ES/PT.
- **Cross-check:** each key is checked against the speech transcript wherever the captions repeat the speech. Expect differences where they don't (e.g. voice-over clips).
- **Format:** the existing `GroundTruth` format with the correct `language`. Use `appearances` where practical.
- **Storage:** gitignored like the existing keys.
- **Fetch script:** `scripts/fetch_eval_samples.py` gains the ten URLs, and `tests/fixtures/eval/README.md` gains their manifest entries (URL, content class, language). The clips themselves never enter the repo.

**D7 — Real-engine check in CI.**
- **What it does:** an unmocked test constructs the engine for every language panoscribe maps, under both model sets, on CPU. It runs one synthetic image through it: rendered text with that language's diacritics where it has them, asserting non-empty output.
- **Unit tests:** the mapping (ISO code → per-set parameters) also gets ordinary unit tests.
- **Where it runs** *(PO call)*: one Linux CI job, on every PR, as a required check. Downloaded models are cached, keyed on the rapidocr version. The CPU path is the same library code on Windows, so Windows is not required for this check.
- **Left to the builder:** the caching mechanics, and whether this is a separate job or part of `test`.

**D8 — #183 and #184.** Both are independent of D1–D7. The plan quotes their acceptance criteria verbatim from the issues.
- **#183, check remote speech settings before download.** Build the speech engine once, before any download (video and photo paths), and reuse it.
  - With `PANO_ASR_BACKEND=remote` and a missing model setting, `transcribe` fails before `download_video` is called (asserted in a test).
  - `transcribe-many` stops before the first download and leaves the items `pending`.
  - Local runs are unchanged.
- **#184, show why a batch item failed.** `transcribe-many` prints one line per failed item (shortened source plus `str(e)`, never the exception chain) through the progress console.
  - At the end it prints a summary: done / failed / pending, plus the state-file path.
  - Exit codes are unchanged.
  - A CLI test captures the output.

**D9 — Docs and release.** Update:
- the README OCR-knobs paragraph: model sets, PP-OCRv6, the version range;
- the `docs/troubleshooting.md` section added in #180: it now describes 0.8.1 only;
- the CHANGELOG.

Then release v0.10.0 per `docs/release-process.md`.

### New clips (picked and checked 2026-11-08; contact sheets were reviewed by the PO)

| Lang | YouTube Short | Channel | Length | Why it's useful |
|---|---|---|---|---|
| FR | `GJslGyaVJ-k` | franceinfo | 95 s | Plain white subtitles, low contrast on pastel; quote card with `[On]` |
| FR | `nBS3iLeiByU` | franceinfo | 78 s | Several caption styles, title cards, split screens |
| ES | `XWQffp7qhRQ` | BBC News Mundo | 70 s | White on dark box; ñ, ¿? |
| ES | `hjhaUcMtLX4` | AJ+ Español | 76 s | Stylised font in 1–3 word chunks, yellow highlights |
| ES | `7CKdfTeIoXo` | BBC News Mundo | 30 s | Headline boxes over busy crowds; captions don't repeat speech |
| PT | `7lxiYXA_hwk` | BBC News Brasil | 29 s | Red caption boxes over red overlay; ã, ç |
| PT | `-prSdejMkaI` | BBC News Brasil | 112 s | Colour-coded speakers, busy backgrounds, italic species names |
| PT | `q9xy46qE94I` | BBC News Brasil | 84 s | Three caption styles, cyan on bright backgrounds |
| EN | `3JbCfZGd2Sk` | BBC News | 67 s | Karaoke captions with red keyword box |
| DE | `JIeiriHBI2w` | tagesschau | 45 s | Bare white text with no box; umlauts, „ “ quotes, "Tourist:innen" |

Rejected: franceinfo `CjBu0Syr97c` (child-abuse topic, deliberately censored words).

## Suggested order of work *(PO call; the plan may change it)*

1. **#183 and #184.** Independent and small; can merge first.
2. **D1–D4 + D7.** Library bump, model sets with `classic` as default, real-engine CI check. It replaces the #180 cap without changing results.
3. **D5–D6.** Answer keys, measurement report, and, only if the rule passes, the default switch to `v6`.
4. **D9.** Docs, then the v0.10.0 release.

**Release gate** *(PO call)*: v0.10.0 waits until the measurement is done, whatever its verdict. If the rule fails, the release ships with `classic` as default and `v6` as an opt-in. There is no urgency: 0.9.0 works for fresh installs.

## Left to the builder

- Where the per-set mapping table lives, and its exact shape.
- How the test image is generated, and the CI caching of models.
- Log wording, and the exact error messages (still free of secrets; plain words).
- How `scripts/eval_ocr.py` selects the model set (setting vs flag), as long as the report records which set and library version produced each number.
