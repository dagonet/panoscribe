# OCR v6 measurement report

Measurements for the newer-OCR-library work (`docs/plans/2026-11-08-ocr-newer-library-design.md`).
Each section records what the real engine does for every language value that
`_ISO_TO_LANGREC` can produce, so later sections can be compared against it.
Numbers in the sections up to the CI engine check come from `scripts/probe_ocr_languages.py` (CPU, real engine, one
rendered image per language); the last section, the real-clip D5 measurement and the default decision, comes from
`scripts/eval_ocr.py` and `scripts/summarize_eval.py`.

## 3.8.1 baseline

Recorded on `feat/ocr-model-sets` with the unchanged lock: `importlib.metadata.version("rapidocr")` = **3.8.1**,
`python scripts/probe_ocr_languages.py` (no `--model-set`, because `ocr_model_set` does not exist yet).
This table defines "works today" and the classic detector per language (design D3, D3a).

14 distinct `LangRec` values are mapped. **3 start and 11 fail to start** on 3.8.1.

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | en_PP-OCRv3_det_mobile.onnx | en_PP-OCRv4_rec_mobile.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | no | | | Привет мир 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| cyrillic | no | | | Добър ден 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ch | yes | ch_PP-OCRv4_det_mobile.onnx | ch_PP-OCRv4_rec_mobile.onnx | 你好世界 2026 | 你好世界2026 | |
| japan | no | | | こんにちは世界 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| korean | no | | | 안녕하세요 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| arabic | no | | | مرحبا بالعالم 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| devanagari | no | | | नमस्ते दुनिया 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| th | no | | | สวัสดีชาวโลก 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| el | no | | | Καλημέρα κόσμε 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ta | no | | | வணக்கம் உலகம் 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| te | no | | | హలో ప్రపంచం 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ka | no | | | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |

Observations:

- **Why 11 fail.** rapidocr's own log for each failure reads `Unsupported configuration: ... ocr_version = PP-OCRv4, task_type = det, lang_type = <language>`.
  `RapidOCREngine._ensure_loaded` sets `Det.lang_type` to the recognition language for every
  value except `latin` (which uses `en`). The 3.8.1 detector registry only has `ch`, `en` and `multi`, so any
  other value is rejected while building the *detector*, before a recognition model is chosen. The failures are
  therefore all in detection; recognition support for those languages is not measured here.
- `ka` is `LangRec.KA`, which is **Kannada** in rapidocr (its font is `kannada.ttf`), while panoscribe's ISO `ka` (Georgian)
  maps to it. The probe text for `ka` is therefore Kannada. The ISO mapping looks wrong; it is not changed here.
- `latin` read `ß` as `B` (`GröBe`); `ch` dropped the space before the year. Both are recorded as observed, not as failures.
- Fonts for rendering come from rapidocr's own `fonts:` registry (`rapidocr.utils.vis_res.get_font_path`); every language had one,
  so no row is "no font". Detection and recognition files are read from rapidocr's `Using <path>.onnx` log lines.

## Classic and v6 on rapidocr 3.10

Recorded on `feat/ocr-model-sets` after the bump: `importlib.metadata.version("rapidocr")` = **3.10.0**
(onnxruntime-gpu 1.24.4, CPU provider; no onnxruntime floor change was needed),
`python scripts/probe_ocr_languages.py --model-set classic` and `--model-set v6`.
The probe passes the `LangRec` values, not ISO codes, so under `v6` only `en`, `ch` and `japan` have a
PP-OCRv6 code; the other values take the automatic per-language fallback to the classic models (design D3).
The ISO-coded v6 path (`de`, `fr`, ...) is shown in the second half of this section.

**All 14 values start under both sets** (3.8.1 baseline: 3 of 14).

What changed against the 3.8.1 baseline, and why:

- **11 languages fixed.** `_ensure_loaded` used to pass the recognition language as `Det.lang_type`; the detector
  registry only has `ch`, `en` and `multi`. The detector is now chosen on its own: `en` for `en`/`latin`, `ch` for
  `ch`/`chinese_cht`/`japan`, `multi` for every other script.
- **`eslav`, `th`, `el`** use PP-OCRv5 mobile recognition (PP-OCRv4 has no route for them); detection stays PP-OCRv4/v3 `multi`.
- **Arabic needs `python-bidi`.** rapidocr 3.10 refuses to build an Arabic recogniser without its optional `rtl` extra
  (`ModuleNotFoundError: RTL recognition requires the optional dependency 'python-bidi'`), which the first 3.10 probe run hit.
  `pyproject.toml` therefore depends on `rapidocr[rtl]` (adds `python-bidi` 0.6.12 to the lock).
- **`en`, `latin`, `ch` are model-for-model identical to the 3.8.1 baseline** (same det and rec files in the classic table).
- **`ka` fixed in the ISO map.** `LangRec.KA` is Kannada; the ISO code `ka` (Georgian) no longer maps to it and `kn` (Kannada) does.
  The probe text for the `ka` value is still Kannada, which is what that model reads.

### rapidocr 3.10.0, `--model-set classic`

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | en_PP-OCRv3_det_mobile.onnx | en_PP-OCRv4_rec_mobile.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | yes | multi_PP-OCRv3_det_mobile.onnx | eslav_PP-OCRv5_rec_mobile.onnx | Привет мир 2026 | Привет м мир 2026 | |
| cyrillic | yes | multi_PP-OCRv3_det_mobile.onnx | cyrillic_PP-OCRv3_rec_mobile.onnx | Добър ден 2026 | Доърден 2о26 | |
| ch | yes | ch_PP-OCRv4_det_mobile.onnx | ch_PP-OCRv4_rec_mobile.onnx | 你好世界 2026 | 你好世界2026 | |
| japan | yes | ch_PP-OCRv4_det_mobile.onnx | japan_PP-OCRv4_rec_mobile.onnx | こんにちは世界 2026 | こんにちは世界 2026 | |
| korean | yes | multi_PP-OCRv3_det_mobile.onnx | korean_PP-OCRv4_rec_mobile.onnx | 안녕하세요 2026 | 2026 | |
| arabic | yes | multi_PP-OCRv3_det_mobile.onnx | arabic_PP-OCRv4_rec_mobile.onnx | مرحبا بالعالم 2026 | 20 26 لاعلابابت اح | |
| devanagari | yes | multi_PP-OCRv3_det_mobile.onnx | devanagari_PP-OCRv4_rec_mobile.onnx | नमस्ते दुनिया 2026 | Phh | |
| th | yes | multi_PP-OCRv3_det_mobile.onnx | th_PP-OCRv5_rec_mobile.onnx | สวัสดีชาวโลก 2026 | | |
| el | yes | multi_PP-OCRv3_det_mobile.onnx | el_PP-OCRv5_rec_mobile.onnx | Καλημέρα κόσμε 2026 | Καλημέρα κόσμε 2026 | |
| ta | yes | multi_PP-OCRv3_det_mobile.onnx | ta_PP-OCRv4_rec_mobile.onnx | வணக்கம் உலகம் 2026 | வண ககம் உல் லகம்ஜ 2026 | |
| te | yes | multi_PP-OCRv3_det_mobile.onnx | te_PP-OCRv4_rec_mobile.onnx | హలో ప్రపంచం 2026 | హలో Ogం&థి | |
| ka | yes | multi_PP-OCRv3_det_mobile.onnx | ka_PP-OCRv4_rec_mobile.onnx | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | ಜಗತು 2026 | |

### rapidocr 3.10.0, `--model-set v6`

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | yes | multi_PP-OCRv3_det_mobile.onnx | eslav_PP-OCRv5_rec_mobile.onnx | Привет мир 2026 | Привет м мир 2026 | |
| cyrillic | yes | multi_PP-OCRv3_det_mobile.onnx | cyrillic_PP-OCRv3_rec_mobile.onnx | Добър ден 2026 | Доърден 2о26 | |
| ch | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | 你好世界 2026 | 你好世界 2026 | |
| japan | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | こんにちは世界 2026 | こんにちは世界 2026 | |
| korean | yes | multi_PP-OCRv3_det_mobile.onnx | korean_PP-OCRv4_rec_mobile.onnx | 안녕하세요 2026 | 2026 | |
| arabic | yes | multi_PP-OCRv3_det_mobile.onnx | arabic_PP-OCRv4_rec_mobile.onnx | مرحبا بالعالم 2026 | 20 26 لاعلابابت اح | |
| devanagari | yes | multi_PP-OCRv3_det_mobile.onnx | devanagari_PP-OCRv4_rec_mobile.onnx | नमस्ते दुनिया 2026 | Phh | |
| th | yes | multi_PP-OCRv3_det_mobile.onnx | th_PP-OCRv5_rec_mobile.onnx | สวัสดีชาวโลก 2026 | | |
| el | yes | multi_PP-OCRv3_det_mobile.onnx | el_PP-OCRv5_rec_mobile.onnx | Καλημέρα κόσμε 2026 | Καλημέρα κόσμε 2026 | |
| ta | yes | multi_PP-OCRv3_det_mobile.onnx | ta_PP-OCRv4_rec_mobile.onnx | வணக்கம் உலகம் 2026 | வண ககம் உல் லகம்ஜ 2026 | |
| te | yes | multi_PP-OCRv3_det_mobile.onnx | te_PP-OCRv4_rec_mobile.onnx | హలో ప్రపంచం 2026 | హలో Ogం&థి | |
| ka | yes | multi_PP-OCRv3_det_mobile.onnx | ka_PP-OCRv4_rec_mobile.onnx | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | ಜಗತು 2026 | |

In the v6 table, 11 of 14 values fell back to the classic models (`en`, `ch` and `japan` use PP-OCRv6 small; `latin` has no v6
code, which is the Review Focus 1 case). The remaining rows are identical to the classic table by design (D3).

### ISO-coded languages (what a `de`/`fr`/... configuration or auto-detection sends)

One synthetic line per language, real engine on CPU, rapidocr 3.10.0 (scratch check, not part of the probe script):

| ocr_language | set | det model | rec model | recognised | rendered |
|---|---|---|---|---|---|
| de | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | GröBe Straße über 2026 | Größe Straße über 2026 |
| de | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Größe Straße über 2026 | Größe Straße über 2026 |
| fr | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | 'école  Noél 2026 | Élève à l'école Noël 2026 |
| fr | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Élève à e à l'école Noël 1 2026 | Élève à l'école Noël 2026 |
| es | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | El nino comio pina   2026 | El niño comió piña 2026 |
| es | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | El niño comió piña 2026 | El niño comió piña 2026 |
| pt | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | 2026 | Ação e informação 2026 |
| pt | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Ação e  informação 2026 | Ação e informação 2026 |
| it | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | Perché  la citta  2026 | Perché la città 2026 |
| it | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Perché la città 2026 | Perché la città 2026 |
| en | classic | en_PP-OCRv3_det_mobile | en_PP-OCRv4_rec_mobile | Hello world 2026 | Hello world 2026 |
| en | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Hello world 2026 | Hello world 2026 |
| zh | classic | ch_PP-OCRv4_det_mobile | ch_PP-OCRv4_rec_mobile | 你好世界2026 | 你好世界 2026 |
| zh | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | 你好世界 2026 | 你好世界 2026 |
| ja | classic | ch_PP-OCRv4_det_mobile | japan_PP-OCRv4_rec_mobile | こんにちは世界 2026 | こんにちは世界 2026 |
| ja | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | こんにちは世界 2026 | こんにちは世界 2026 |

These are single synthetic lines (one font, one size), a start-up and sanity check only. They say nothing about quality on
real clips; that is the D5 measurement.
Rows where the recognised text is empty or far from the probe text (`th`, `devanagari`, `te`, `ka`, `korean` without its Hangul) show the
engine starts but that the synthetic line is not read; they are recorded as observed, not as failures of this change.

## Engine check in CI (`tests/test_ocr_engine_real.py`, job `ocr-engine`)

`uv run pytest -m engine -v` builds the real engine (CPU) for every `PROBE_TEXT` language under both sets. The start
check is a hard requirement for all 28 cases. The text check (non-empty, and a 4-character run shared with the probe
text *without* its trailing year, because every model reads digits and the year alone would let a model that cannot read
the script pass; Arabic is compared in display order, which is what rapidocr returns) failed for several languages with
the original 60 px / 40 px-margin image, so the probe image was changed once: the margin went from 40 to 100 px
(60 px text; 100 and 160 px text, and a 150 px margin, read no better and Thai worse). Effect on the text check
(classic and v6 behave the same for these languages, whose models are identical in both sets):

| language | 40 px margin | 100 px margin |
|---|---|---|
| th | not read (0 boxes) | read in full |
| ka | `ಜಗತು 2026` | `ನಮಸಾರ ಜಗತುೃ 2026`, passes |
| arabic | `20 26 لاعلابابت اح` | `2026 ملاعلاب ابحرف`, passes once compared in display order |
| devanagari | `Phh` | `नमरते I? 202५`, still misread |
| te | `హలో Ogం&థి` | `హలో Ogం&థ! కంళం`, still misread |
| korean | `2026` | `2026`, no Hangul at any size or margin |

Known weak (engine starts, text not read; `xfail(strict=False, raises=TextNotReadError)`, both sets): **korean**, **devanagari**,
**te**. Korean is rendered in rapidocr's Korean font, a handwriting face; the Task 5 probe saw the Hangul at 0.53
confidence, below panoscribe's 0.6 filter, which is left as it is. No production OCR setting was changed for any of this.

Model sizes (rapidocr 3.10.0 downloads, KiB): `en` classic = det 2365 + rec 7474 + cls 572; `latin` rec 8768;
`ch` classic = det 4634 + rec 10603; PP-OCRv6 small = det 9697 + rec 20737. The Dockerfile bakes in those four
configs, **63.3 MiB** in total.

## Real-clip measurement: `classic` vs `v6` (design D5)

**Verdict in plain words: the default stays `classic`.** On the 15 clips, PP-OCRv6 does not clear the D5 rule. It
is about as good as `classic` for English, German, Spanish and Portuguese recall, and it reads accents better in a few
entries (`Ü`, `é`, `ç` and `î` come out where `classic` drops them). But it loses recall on French (0.887 against 0.918,
more than the 0.02 allowed), it leaves more unmatched text on French and Portuguese than `classic`, and its pooled recall
over all 15 clips is lower (0.964 against 0.970). German passes with or without the dense sample 1, so the German
question (R23) does not change the outcome. `v6` is also slower: about 1.29x the total runtime of `classic` on CPU,
below the 2x flag. `v6` stays available as an opt-in (`PANO_OCR_MODEL_SET=v6`).

### What was run

- Host: the Linux agent host, CPU only (`PANO_OCR_DEVICE=cpu`), rapidocr 3.10.0 for both sets, panoscribe at `1215e4a`.
- Clips: 15 samples, 12 videos and 3 photo posts (1, 4, 5, run with `--images`). Languages come from each key's
  `language` field: de = 1, 3, 5, 16; en = 4, 6, 15; fr = 7, 8; es = 9, 10, 11; pt = 12, 13, 14 (sample 2 no longer exists).
  Answer keys are the gitignored `gt-sample-N.json` after the Task 8 consistency pass; they were not touched after any OCR output was seen.
- Command per clip and set: `PANO_OCR_MODEL_SET=<set> PANO_OCR_DEVICE=cpu uv run python scripts/eval_ocr.py <clip> <key> --junk --output <dir>/sample-N-<set>.json`.
  Tables below are `uv run python scripts/summarize_eval.py <dir>` verbatim. Runs were sequential, `classic` then `v6` for each clip.
- v6 really ran the v6 models for all five languages: every `v6` log shows `PP-OCRv6_det_small.onnx` + `PP-OCRv6_rec_small.onnx`
  (also for the Latin-script ISO codes `de`, `fr`, `es`, `pt`), and every `classic` log shows `en_PP-OCRv3_det_mobile` + `latin_PP-OCRv3_rec_mobile`
  (`en_PP-OCRv4_rec_mobile` for English).
- **Sample 16 (R24).** The original `sample-16.mp4` is AV1 and `cv2.VideoCapture` in this environment cannot decode it
  (`sample_frames` yields 0 frames). It was renamed `sample-16.av1.mp4` and transcoded with ffmpeg to H.264 (`yuv420p`,
  crf 18, 1080x1920 at 25 fps, AAC audio) as `sample-16.mp4`; `sample_frames` yields 44 frames (about the 45 expected for
  44.8 s at 1 fps). `classic`, `v6` and the 3.8.1 run all use this same file.

### Determinism (D5 "Run noise")

`classic` on sample 12 (pt video), run twice: the two output JSONs are byte-identical (`cmp`), so sampling and CPU inference are
deterministic and every configuration was run **once**. (Wall time of the two runs: 15.1 s and 15.0 s.)

### Library-bump check: rapidocr 3.8.1 vs 3.10.0, `classic`

3.8.1 = tag `v0.9.0` in a detached worktree synced with `uv sync --frozen --extra dev --extra api --extra photo`
(rapidocr 3.8.1; its `eval_ocr.py` has no `--model-set`, so it ran as shipped), same clips and keys, same CPU setting.
Its JSON has no `ocr_model_set` field, so the comparison is per clip on `recall`, `precision` and the per-entry matched flags.

| sample | 3.8.1 recall | 3.10 classic recall | delta | 3.8.1 precision | 3.10 precision | entries matched differently |
|---|---|---|---|---|---|---|
| 1 | 0.9957 | 0.9957 | +0.0000 | 0.9834 | 0.9834 | 0 (best candidate text differs for 0) |
| 3 | 1.0000 | 1.0000 | +0.0000 | 0.5370 | 0.5370 | 0 (best candidate text differs for 0) |
| 4 | 1.0000 | 1.0000 | +0.0000 | 0.9828 | 0.9828 | 0 (best candidate text differs for 0) |
| 5 | 1.0000 | 1.0000 | +0.0000 | 0.8824 | 0.8824 | 0 (best candidate text differs for 0) |
| 6 | 0.9286 | 0.9286 | +0.0000 | 0.4479 | 0.4479 | 0 (best candidate text differs for 0) |
| 7 | 1.0000 | 1.0000 | +0.0000 | 0.6796 | 0.6796 | 0 (best candidate text differs for 0) |
| 8 | 0.8806 | 0.8806 | +0.0000 | 0.5987 | 0.5987 | 0 (best candidate text differs for 0) |
| 9 | 0.9545 | 0.9545 | +0.0000 | 0.4453 | 0.4453 | 0 (best candidate text differs for 0) |
| 10 | 0.9180 | 0.9180 | +0.0000 | 0.2196 | 0.2196 | 0 (best candidate text differs for 0) |
| 11 | 1.0000 | 1.0000 | +0.0000 | 0.5938 | 0.5938 | 0 (best candidate text differs for 0) |
| 12 | 1.0000 | 1.0000 | +0.0000 | 0.6098 | 0.6098 | 0 (best candidate text differs for 0) |
| 13 | 0.9710 | 0.9710 | +0.0000 | 0.6562 | 0.6562 | 0 (best candidate text differs for 0) |
| 14 | 1.0000 | 1.0000 | +0.0000 | 0.5154 | 0.5154 | 0 (best candidate text differs for 0) |
| 15 | 1.0000 | 1.0000 | +0.0000 | 0.7009 | 0.7009 | 0 (best candidate text differs for 0) |
| 16 | 0.9474 | 0.9474 | +0.0000 | 0.5283 | 0.5283 | 0 (best candidate text differs for 0) |

Largest per-clip recall difference: 0.0000 (the Step 1 spread is 0). **The library bump alone changes nothing**, as intended:
`classic` on 3.10 reads every clip exactly as 3.8.1 did. The 3.8.1 baseline used the same `en_PP-OCRv3_det_mobile` +
`latin_PP-OCRv3_rec_mobile` pair (checked in the sample-12 log). Total wall time: 542.6 s on 3.8.1, 556.9 s on 3.10 `classic`.

### `summarize_eval.py` output (all 15 clips)

#### Per clip

| clip | language | model set | recall | raw recall | unmatched rate | segments |
|---|---|---|---|---|---|---|
| sample-1 | de | classic | 232/233 = 0.996 | 0.749 | 0.417 | 302 |
| sample-1 | de | v6 | 232/233 = 0.996 | 0.749 | 0.415 | 301 |
| sample-16 | de | classic | 18/19 = 0.947 | 0.474 | 0.811 | 53 |
| sample-16 | de | v6 | 18/19 = 0.947 | 0.474 | 0.778 | 45 |
| sample-3 | de | classic | 11/11 = 1.000 | 0.182 | 0.889 | 54 |
| sample-3 | de | v6 | 11/11 = 1.000 | 0.182 | 0.889 | 54 |
| sample-5 | de | classic | 18/18 = 1.000 | 0.000 | 0.882 | 68 |
| sample-5 | de | v6 | 18/18 = 1.000 | 0.000 | 0.875 | 64 |
| sample-15 | en | classic | 49/49 = 1.000 | 0.959 | 0.336 | 107 |
| sample-15 | en | v6 | 49/49 = 1.000 | 0.959 | 0.457 | 105 |
| sample-4 | en | classic | 34/34 = 1.000 | 0.471 | 0.724 | 58 |
| sample-4 | en | v6 | 34/34 = 1.000 | 0.471 | 0.729 | 59 |
| sample-6 | en | classic | 26/28 = 0.929 | 0.714 | 0.623 | 326 |
| sample-6 | en | v6 | 26/28 = 0.929 | 0.679 | 0.534 | 268 |
| sample-10 | es | classic | 56/61 = 0.918 | 0.344 | 0.933 | 460 |
| sample-10 | es | v6 | 55/61 = 0.902 | 0.344 | 0.929 | 438 |
| sample-11 | es | classic | 6/6 = 1.000 | 0.000 | 0.906 | 32 |
| sample-11 | es | v6 | 6/6 = 1.000 | 0.000 | 0.972 | 36 |
| sample-9 | es | classic | 21/22 = 0.955 | 0.091 | 0.912 | 137 |
| sample-9 | es | v6 | 21/22 = 0.955 | 0.091 | 0.847 | 131 |
| sample-7 | fr | classic | 30/30 = 1.000 | 0.400 | 0.495 | 206 |
| sample-7 | fr | v6 | 28/30 = 0.933 | 0.400 | 0.500 | 126 |
| sample-8 | fr | classic | 59/67 = 0.881 | 0.414 | 0.809 | 157 |
| sample-8 | fr | v6 | 58/67 = 0.866 | 0.414 | 0.803 | 147 |
| sample-12 | pt | classic | 9/9 = 1.000 | 0.222 | 0.780 | 41 |
| sample-12 | pt | v6 | 9/9 = 1.000 | 0.222 | 0.833 | 36 |
| sample-13 | pt | classic | 67/69 = 0.971 | 0.306 | 0.777 | 224 |
| sample-13 | pt | v6 | 67/69 = 0.971 | 0.306 | 0.803 | 203 |
| sample-14 | pt | classic | 20/20 = 1.000 | 0.000 | 0.854 | 130 |
| sample-14 | pt | v6 | 20/20 = 1.000 | 0.050 | 0.957 | 116 |

#### Per language

| language | model set | clips | recall | raw recall | unmatched rate | segments |
|---|---|---|---|---|---|---|
| de | classic | 4 | 279/281 = 0.993 | 0.660 | 0.581 | 477 |
| de | v6 | 4 | 279/281 = 0.993 | 0.660 | 0.569 | 464 |
| en | classic | 3 | 109/111 = 0.982 | 0.748 | 0.572 | 491 |
| en | v6 | 3 | 109/111 = 0.982 | 0.739 | 0.542 | 432 |
| es | classic | 3 | 83/89 = 0.933 | 0.258 | 0.927 | 629 |
| es | v6 | 3 | 82/89 = 0.921 | 0.258 | 0.914 | 605 |
| fr | classic | 2 | 89/97 = 0.918 | 0.410 | 0.631 | 363 |
| fr | v6 | 2 | 86/97 = 0.887 | 0.410 | 0.663 | 273 |
| pt | classic | 3 | 96/98 = 0.980 | 0.236 | 0.803 | 395 |
| pt | v6 | 3 | 96/98 = 0.980 | 0.246 | 0.856 | 355 |

#### Verdict (D5, pooled, exactly as computed by the script)

```
FAIL: classic stays the default.
- fr: recall v6 0.887 < classic 0.918 - 0.02
- fr: unmatched_rate v6 0.663 > classic 0.631 + 0.02
- pt: unmatched_rate v6 0.856 > classic 0.803 + 0.02
- overall: pooled recall v6 0.964 < classic 0.970
```

Reading it: EN, DE and ES pass on both recall and junk (ES recall is 0.012 lower, inside the 0.02 margin). FR fails on
recall and on junk. PT keeps its recall (96/98 both) but fails on junk (+0.053). The overall pooled recall is lower by 0.006,
which the rule does not allow (the rule has no margin on that line).

### German without sample 1 (R23)

Sample 1 is a dense infographic photo post with 233 of German's 281 required texts, so it dominates the pooled German number.
The same script was run on a results directory without `sample-1-*.json` (no change to the script or the rule):

| language | model set | clips | recall | raw recall | unmatched rate | segments |
|---|---|---|---|---|---|---|
| de | classic | 3 | 47/48 = 0.979 | 0.229 | 0.863 | 175 |
| de | v6 | 3 | 47/48 = 0.979 | 0.229 | 0.853 | 163 |

German per clip (from the per-clip table above):

| clip | model set | recall | raw recall | unmatched rate | segments |
|---|---|---|---|---|---|
| sample-1 | classic | 232/233 = 0.996 | 0.749 | 0.417 | 302 |
| sample-1 | v6 | 232/233 = 0.996 | 0.749 | 0.415 | 301 |
| sample-3 | classic | 11/11 = 1.000 | 0.182 | 0.889 | 54 |
| sample-3 | v6 | 11/11 = 1.000 | 0.182 | 0.889 | 54 |
| sample-5 | classic | 18/18 = 1.000 | 0.000 | 0.882 | 68 |
| sample-5 | v6 | 18/18 = 1.000 | 0.000 | 0.875 | 64 |
| sample-16 | classic | 18/19 = 0.947 | 0.474 | 0.811 | 53 |
| sample-16 | v6 | 18/19 = 0.947 | 0.474 | 0.778 | 45 |

German passes in both views (equal recall, v6 junk lower by 0.010). The script's overall verdict on that directory is also
`FAIL` (fr recall and junk, pt junk, and pooled recall v6 0.948 < classic 0.957), with exactly the same failing lines
for FR and PT. So the pooled verdict and the "DE without sample 1" verdict **agree**, and R23 does not block anything.

### What changed between the sets, text by text

Required entries that exactly one set matched, taken from the two result JSONs of each clip:

| clip | lost by v6 | gained by v6 | missed by both |
|---|---|---|---|
| 1 (de) | 1 (key entry #203, a single word on an infographic) | 1 (#172, a word with an umlaut) | 0 |
| 7 (fr) | 2 (#5, a location and date tag; #16, a short subtitle line) | 0 | 0 |
| 8 (fr) | 3 (#28, #41, #52: subtitle lines) | 2 (#39, #64: subtitle lines) | 6 (#12, #15, #21, #25, #47, #54) |
| 10 (es) | 3 (#55, #57, #60: caption lines) | 2 (#38, #49: caption lines) | 3 (#43, #45, #47) |
| 6 (en) | 0 | 0 | 2 (#0, #42) |
| 9, 13, 16 | 0 | 0 | 1 (#14), 2 (#24, #35), 1 (#15) |
| 3, 4, 5, 11, 12, 14, 15 | 0 | 0 | 0 |

Entry numbers are 0-based positions in the clip's answer key (`expected_texts` order). Neither the key texts nor the OCR
reads are quoted here: the clips and keys are third-party material that stays out of the repository.

The pattern in these few entries: in some gained entries (samples 1, 8 and 10) `v6` returned accented characters that `classic`
had dropped or flattened. In the lost entries it produced garbled or partial lines, a line missing its first words, or a stray
number in front of a word. It also yields fewer segments overall (e.g. sample 7: 126 against 206, French 273 against 363),
yet the unmatched share does not fall for French and Portuguese.

### Raw stage vs after the filters (D5 "Raw vs filtered")

`raw recall` in the tables is `junk.raw.retained_overlay_recall`: the share of required texts that a *single* segment
matches before the UI/frequency filters and dedup run. It counts no pair or triple of segments, so it is far below the
scored recall (e.g. sample 5: raw 0.000, scored 1.000) and is not comparable across clips.
Compared between the sets it is equal for DE (0.660), ES (0.258) and FR (0.410), 0.009 lower for `v6` in EN
(0.739 against 0.748) and 0.010 higher in PT (0.246 against 0.236). So at the raw stage `v6` is not worse in any language
by more than a point, while after the pipeline FR is 0.031 and ES 0.012 lower. This metric cannot say whether the
French loss comes from filters tuned for the old model or from the model reading less; the entry-by-entry list above shows
both `v6` misreads (garbled or partial lines) and a caption read with its date placed in front. Pinning that down would be the filter-retuning
follow-up named in the non-goals; it is not part of this decision.

### Runtime

One run per configuration, sequential, on a shared host (load average 3 to 8 from other sessions during the runs), so each
figure carries roughly 10 to 20 percent noise. `v6` ran right after `classic` for each clip.

| clip | language | classic (s) | v6 (s) | v6 / classic |
|---|---|---|---|---|
| sample-1 | de | 10.9 | 11.3 | 1.04x |
| sample-3 | de | 4.2 | 3.9 | 0.95x |
| sample-4 | en | 6.6 | 6.0 | 0.91x |
| sample-5 | de | 4.7 | 5.7 | 1.20x |
| sample-6 | en | 153.7 | 209.1 | 1.36x |
| sample-7 | fr | 51.9 | 66.2 | 1.27x |
| sample-8 | fr | 37.9 | 49.1 | 1.30x |
| sample-9 | es | 36.4 | 50.9 | 1.40x |
| sample-10 | es | 49.1 | 75.8 | 1.55x |
| sample-11 | es | 20.9 | 22.6 | 1.08x |
| sample-12 | pt | 14.5 | 18.6 | 1.28x |
| sample-13 | pt | 71.8 | 77.6 | 1.08x |
| sample-14 | pt | 42.0 | 52.9 | 1.26x |
| sample-15 | en | 32.2 | 42.2 | 1.31x |
| sample-16 | de | 20.0 | 26.1 | 1.31x |
| total | | 556.9 | 718.0 | 1.29x |

`v6` is **not** more than 2x slower (worst clip 1.55x, total 1.29x), so no speed flag. Speed is not part of the rule.

### Notes and caveats

- **Portuguese (R20).** In Task 6, `v6` found no text boxes on the synthetic line `Coração ação português 2026` while
  `classic` read it. That was an early warning for Portuguese. The real clips only half confirm it: Portuguese **recall is
  unchanged** (96/98 for both sets, the same three clips each at 1.000, 0.971, 1.000), but `v6` leaves more unmatched text
  (0.856 against 0.803; sample 14: 0.957 against 0.854) and produces fewer segments (355 against 395). This is the line that
  fails the junk rule for PT. The synthetic ISO table above shows `v6` reading another Portuguese line (`Ação e informação 2026`) that `classic`
  missed, so the Task 6 miss does not extend to every Portuguese line.
- **Reachability of the keys (R25).** The Task 8 sampler-reachability audit was complete only for samples 10 and 15; the
  other keys may list sub-second chunks the 1 fps sampler never shows. Both sets are scored against the same key and the
  same sampled frames, so the classic-versus-v6 comparison per clip is symmetric, but **absolute recall is not comparable
  across clips** (and a language's absolute recall depends on how many unreachable entries its keys hold).
  Only the differences between the sets carry information.
- **Unmatched rate is relative.** The keys list the overlay text, not background text, signs or watermarks, so unmatched rates of
  0.5 to 0.97 are normal for both sets; only the difference between `classic` and `v6` is meaningful.
- **Small samples.** FR has two clips and 97 required texts; one lost text is about 0.010 of its recall. The French
  recall miss is about one text beyond the margin, and PT's junk miss comes mainly from clips 12 and 14.
- **Sample 2** no longer exists; the German key set is 1, 3, 5 and 16, with sample 1 carrying 233 of its 281 texts.
- **Languages that failed to start on 3.8.1.** 11 of the 14 mapped `LangRec` values failed (the baseline section above):
  eslav, cyrillic, japan, korean, arabic, devanagari, th, el, ta, te and ka. Only `en`, `latin` and `ch` started. All 14 start on 3.10
  under both sets; none of these 11 is part of the D5 rule (the five measured languages all use the `latin`, `en` or v6 route).

### Known limitations (not part of the rule)

- Korean, Hindi (Devanagari) and Telugu are read weakly by both sets (R12; `xfail` in `tests/test_ocr_engine_real.py`).
- Arabic text comes back in display order from rapidocr (issue #188).

### Decision

`classic` stays the default. `ocr_model_set` is unchanged (`"classic"`). `v6` remains an opt-in through `PANO_OCR_MODEL_SET=v6`.
Reopening it would take (a) more French and Portuguese clips, or (b) the filter/dedup retuning follow-up, then this same
measurement again (`scripts/summarize_eval.py`).
